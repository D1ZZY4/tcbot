# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Leaveall and cleanup maintenance commands."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pyrogram import Client
from pyrogram.types import Message

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.database.types import as_int
from tcbot.modules.helper import decorators, messages
from tcbot.modules.helper.context import Ctx, bot_identity, display_name
from tcbot.modules.helper.handlers import MessageHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    replies,
    reply_rich,
    reply_rich_result,
    safe_edit,
    send_log,
)
from tcbot.modules.helper.pipelines import moderation_enforcement
from tcbot.modules.helper.pipelines.errors.exceptions import API_REFUSAL_ERRORS
from tcbot.modules.helper.rich.block import blocks
from tcbot.utils.dispatch import (
    fan_out,
    gather_bounded,
    is_circuit_skip,
    throw_if_cancelled,
)
from tcbot.utils.i18n import Safe, bold, code, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)


# * Bound for one membership probe; single owner in the transport module.
_MEMBERSHIP_CHECK_TIMEOUT = TELEGRAM_LOOKUP_TIMEOUT


__module_name__ = "Maintenance"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("maintenance.help.overview", locale),
        commands=t("maintenance.help.commands.body", locale),
        who=(
            f"{bold('/leaveall')}: {replies.perm_owner_only(locale, plain=False)}\n"
            f"{bold('/cleanup')}: {replies.perm_staff_only(locale, plain=False)}\n"
            f"{bold('/tcrepair')}: {replies.perm_staff_only(locale, plain=False)}\n"
            f"{bold('/tcforget')}: {replies.perm_owner_only(locale, plain=False)}"
        ),
        where=replies.context_bot_or_group(locale),
        details=[
            ("/leaveall", t("maintenance.help.leaveall.body", locale)),
            ("/cleanup", t("maintenance.help.cleanup.body", locale)),
            ("/tcrepair", t("maintenance.help.repair.body", locale)),
            ("/tcforget", t("maintenance.help.forget.body", locale)),
        ],
        target=False,
        examples=t("maintenance.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()


# ────────────────── Command Leave All </leaveall> ───────────────── #

# * Primary groups (main_group) are required federation destinations and are
# * seeded into the connected-group registry at startup. They must not be
# * torn down by leaveall / cleanup / disconnect / rmtc paths. Guarded by
# * cfg.is_primary_group (single source of truth in tcbot/__init__.py) at
# * every call site below.


@dataclass(frozen=True)
class _LeaveResult:
    """Result of a single ``_leave_one`` operation, one field per side-effect.

    The structured fields let ``cmd_leaveall`` count success and failure
    per side-effect instead of inspecting a raw ``gather`` tuple. The DB
    deactivation is the authoritative state write; a successful
    ``leave_chat`` with a failed ``deactivate_group`` would leave a
    "ghost" group in the database (still active but the bot has left),
    so the leave counts as failed when either side-effect fails.
    """

    chat_id: int
    left: bool
    deactivated: bool
    log_sent: bool

    @property
    def ok(self) -> bool:
        """A leave is considered successful only when BOTH Telegram and DB agree."""
        return self.left and self.deactivated


async def _leave_one(
    bot: Client,
    grp: GroupDoc,
    admin_id: int,
    admin_name: str,
) -> _LeaveResult:
    """Leave one group, deactivate it in DB, and post a disconnection log.

    The three operations fire in parallel; the result is wrapped in a
    structured :class:`_LeaveResult` so the caller can count each
    side-effect independently. ``deactivate_group`` is the authoritative
    state write -- a "ghost" group (bot left, DB still active) is
    counted as failed.
    """
    chat_id = grp.get("chat_id")
    title = grp.get("title", "Unknown")
    if chat_id is None:
        # * Defensive: active_groups rows always carry chat_id, but a
        # * malformed row must count as a failed leave, not raise inside
        # * fan_out (which would surface as a bare BaseException entry).
        log.warning("leaveall: skipping group record without chat_id: %s", title)
        return _LeaveResult(chat_id=0, left=False, deactivated=False, log_sent=False)
    leave_result, deactivate_result, log_result = await asyncio.gather(
        bot.leave_chat(chat_id),
        db.groups_db.deactivate_group(chat_id),
        send_log(
            bot,
            messages.group_disconnected_log(
                chat_id,
                title,
                admin_id,
                admin_name,
            ),
        ),
        return_exceptions=True,
    )
    # ! Cancellation must propagate instead of counting as a ghost failure.
    throw_if_cancelled((leave_result, deactivate_result, log_result))
    if isinstance(leave_result, BaseException):
        log.debug("leave_chat failed for chat %d: %s", chat_id, leave_result)
    if isinstance(deactivate_result, BaseException):
        log.warning(
            "deactivate_group failed for chat %d during leaveall: %s",
            chat_id,
            deactivate_result,
        )
        if not isinstance(leave_result, BaseException):
            # ! CRITICAL: the bot has already left, so the database is the
            # ! only remaining source of truth. Retry the authoritative
            # ! write once; a surviving failure is a ghost group and must
            # ! reach the operator error channel with its chat id.
            try:
                await db.groups_db.deactivate_group(chat_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "leaveall ghost group %d: bot left but deactivation "
                    "failed after retry",
                    chat_id,
                )
            else:
                deactivate_result = None
    if isinstance(log_result, BaseException):
        log.warning(
            "group_disconnected log send failed for %d: %s", chat_id, log_result
        )
    return _LeaveResult(
        chat_id=chat_id,
        left=not isinstance(leave_result, BaseException),
        deactivated=not isinstance(deactivate_result, BaseException),
        log_sent=not isinstance(log_result, BaseException),
    )


@decorators.ratelimiter(decorators.THROTTLE_CRITICAL)
@decorators.owner_only
@decorators.log_execution
async def cmd_leaveall(ctx: Ctx) -> None:
    """Leave all active connected groups and deactivate their DB records.

    Fetches active groups (excluding the primary groups, which are required
    enforcement destinations), fans out individual leave-and-deactivate
    coroutines concurrently (``_leave_one``), then edits the status
    message with the final success/failure counts. A leave counts as
    successful only when both ``leave_chat`` and ``deactivate_group``
    succeed; a partial success (one succeeded, the other failed) is
    counted as a failure so the operator can investigate the ghost.
    """
    admin = ctx.effective_user
    if admin is None:
        return
    locale = await locale_for_update(ctx)
    try:
        all_groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during leaveall")
        status_msg = ctx.effective_message
        if status_msg is not None:
            await reply_rich(
                status_msg,
                replies.err_groups_load_failed(locale, plain=False),
                log_label="leaveall groups-failed",
            )
        return
    # * Never tear down the primary groups. They are in the registry as
    # * required enforcement destinations, but leaveall must keep them
    # * reachable; the explicit guard is defence in depth.
    groups = [g for g in all_groups if not cfg.is_primary_group(g.get("chat_id"))]
    if not groups:
        status_msg = ctx.effective_message
        if status_msg is not None:
            await reply_rich(
                status_msg,
                replies.err_no_connected_groups(locale, plain=False),
                log_label="leaveall no-groups",
            )
        return

    status_msg = ctx.effective_message
    status = None
    if status_msg is not None:
        # * Send a fresh status message and keep it: the final counts edit
        # * this bot-owned message. Editing the user's command message would
        # * always fail (bots cannot edit messages sent by others).
        try:
            status = await reply_rich_result(
                status_msg,
                t("maintenance.status.sending", locale, n=len(groups), plain=True),
            )
        except Exception as exc:
            log.debug("leaveall status reply failed: %s", exc)

    # * Semaphore-bounded to respect Telegram rate limits on large federations.
    all_results = await fan_out(
        [_leave_one(ctx.bot, g, admin.id, display_name(admin)) for g in groups]
    )

    # * ``fan_out`` returns ``T | BaseException`` so a transport error raised
    # * before the gather starts still shows up as an entry.
    # * ``_leave_one`` itself never raises (a malformed row yields a failed
    # * result), but filter defensively before unpacking structured fields,
    # * then count each side-effect independently.
    ok_results = [r for r in all_results if isinstance(r, _LeaveResult)]

    # * Count success per side-effect. A leave is "fully successful" only
    # * when BOTH ``leave_chat`` and ``deactivate_group`` succeed. A
    # * partial state (one succeeded, the other failed) is a ghost and
    # * counts as a failure so the operator can reconcile manually.
    left_ok = sum(1 for r in ok_results if r.ok)
    partial = sum(1 for r in ok_results if (r.left or r.deactivated) and not r.ok)
    log_failed = sum(1 for r in ok_results if not r.log_sent)
    failed = len(groups) - left_ok

    if status is not None:
        detail = ""
        if partial:
            detail += t("maintenance.leaveall.partial", locale, n=partial)
        if log_failed:
            detail += t("maintenance.leaveall.log_failed", locale, n=log_failed)
        try:
            await safe_edit(
                status,
                t(
                    "maintenance.leaveall.done",
                    locale,
                    ok=Safe(code(str(left_ok))),
                    failed=Safe(code(str(failed))),
                    detail=Safe(detail),
                ),
            )
        except Exception:
            log.exception("Leaveall status edit failed")


# ─────────────────── Command CleanUp </cleanup> ─────────────────── #


async def _should_remove(bot: Client, grp: GroupDoc) -> bool:
    """Return True if the bot has left or been kicked from the group.

    Primary groups are never "removable" -- they are managed separately
    and must never be deactivated by cleanup. If ``_should_remove``
    is called for a primary group, it short-circuits to ``False`` so
    ``cmd_cleanup`` skips it.
    """
    chat_id = grp.get("chat_id")
    if chat_id is None:
        return True
    if cfg.is_primary_group(chat_id):
        return False
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id, (await bot_identity(bot)).id),
            timeout=_MEMBERSHIP_CHECK_TIMEOUT,
        )
        status = getattr(member.status, "value", member.status)
        return status in ("left", "kicked")
    except API_REFUSAL_ERRORS as exc:
        # * A bare API refusal is ambiguous, but these specific answers mean
        # * Telegram no longer has the bot in the chat. Keeping such a row
        # * would leave a ghost group in the active federation list forever.
        text = str(exc).lower()
        gone = any(
            marker in text
            for marker in (
                "chat_not_found",
                "user_not_participant",
                "not a member",
                "bot is not a member",
            )
        )
        if gone:
            log.warning(
                "Telegram reports the bot left %d; pruning it in cleanup: %s",
                chat_id,
                exc,
            )
            return True
        # * Any other service refusal means the bot reached Telegram; keep it.
        log.warning(
            "Could not verify membership for %d, keeping group: %s", chat_id, exc
        )
        return False
    except Exception:
        # ! CRITICAL: fail closed by keeping the group, but re-raise so fan_out
        # ! records the transport failure against the shared circuit. Swallowing
        # ! it here would make every timeout look like a successful probe.
        log.exception("Could not verify membership for %d; keeping group", chat_id)
        raise


@decorators.ratelimiter(decorators.THROTTLE_BULK)
@decorators.staff_only
@decorators.log_execution
async def cmd_cleanup(ctx: Ctx) -> None:
    """Prune inaccessible groups from the active federation list.

    Checks all groups concurrently via ``_should_remove`` (which excludes
    primary groups), deactivates the identified stale records in parallel,
    then replies with the count of removed groups.
    """
    reply_msg = ctx.effective_message
    if reply_msg is None:
        return
    locale = await locale_for_update(ctx)
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during cleanup")
        await reply_rich(
            reply_msg,
            replies.err_groups_load_failed(locale, plain=False),
            log_label="cleanup groups-failed",
        )
        return

    # * Semaphore-bounded to respect Telegram rate limits on large federations.
    checks = await fan_out([_should_remove(ctx.bot, g) for g in groups])

    to_remove = [g for g, remove in zip(groups, checks, strict=True) if remove is True]
    # * A failed or skipped probe is not a verified "keep": it must be named in
    # * the staff summary instead of looking like a clean sweep.
    unverified = [
        (grp, result)
        for grp, result in zip(groups, checks, strict=True)
        if isinstance(result, BaseException)
    ]
    for grp, result in unverified:
        log.warning(
            "cleanup probe failed for chat=%s: %s",
            grp.get("chat_id", 0),
            result,
        )
    detail = ""
    if unverified:
        skipped = sum(1 for _grp, result in unverified if is_circuit_skip(result))
        detail = t(
            "maintenance.cleanup.unverified",
            locale,
            n=Safe(code(str(len(unverified) - skipped))),
            skipped=Safe(code(str(skipped))),
        )

    if to_remove:
        # * Pure database writes: bounded gather, not fan_out. fan_out wraps
        # * the Telegram circuit breaker, which must not gate DB work.
        deact_results = await gather_bounded(
            [db.groups_db.deactivate_group(g.get("chat_id", 0)) for g in to_remove]
        )
        deactivated = sum(1 for r in deact_results if r is True)
        for grp, result in zip(to_remove, deact_results, strict=True):
            if isinstance(result, BaseException):
                log.error(
                    "cleanup deactivate failed for chat=%s: %s",
                    grp.get("chat_id", 0),
                    result,
                    exc_info=result,
                )
            elif result is not True:
                log.warning(
                    "cleanup deactivate no-op for chat=%s (record already gone?)",
                    grp.get("chat_id", 0),
                )
    else:
        deactivated = 0

    await reply_rich(
        reply_msg,
        t(
            "maintenance.cleanup.done",
            locale,
            n=Safe(code(str(deactivated))),
            detail=Safe(detail),
        ),
        log_label="cleanup",
    )


# ────────────────── Command Repair </tcrepair> ────────────────── #


def _repair_lines(runs: list[dict[str, object]], locale: str) -> str:
    """Render the unsettled runs as one rich message."""
    lines = [t("maintenance.repair.header", locale, n=len(runs))]
    for run in runs:
        run_id = as_int(run.get("id"))
        applied = as_int(run.get("succeeded_count")) + as_int(run.get("skipped_count"))
        lines.append(
            t(
                "maintenance.repair.line",
                locale,
                run=Safe(code(str(run_id))),
                operation=str(run.get("operation") or ""),
                action_type=str(run.get("action_type") or ""),
                user=Safe(code(str(as_int(run.get("target_user_id"))))),
                status=str(run.get("status") or ""),
                applied=applied,
                total=as_int(run.get("target_count")),
                failed=as_int(run.get("failed_count")),
                exhausted=as_int(run.get("exhausted_targets")),
            )
        )
    lines.append(t("maintenance.repair.footer", locale))
    return blocks("\n".join(lines))


async def _reply_repair_list(msg: Message, locale: str) -> None:
    """Reply with the runs that still need an operator."""
    try:
        runs = await db.enforcement_ledger.list_unsettled_runs()
    except Exception:
        log.exception("list_unsettled_runs failed during tcrepair")
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="tcrepair list-failed",
            parse_mode=None,
        )
        return
    if not runs:
        await reply_rich(
            msg,
            t("maintenance.repair.none", locale, plain=True),
            log_label="tcrepair none",
            parse_mode=None,
        )
        return
    await reply_rich(
        msg,
        _repair_lines(runs, locale),
        log_label="tcrepair list",
    )


@decorators.ratelimiter(decorators.THROTTLE_FEDERATION)
@decorators.staff_only
@decorators.log_execution
async def cmd_repair(ctx: Ctx) -> None:
    """List the unsettled enforcement runs, or re-drive one failed group.

    The enforcement ledger retries transient failures on its own, but a
    target that exhausts its attempts is terminal. This command is the
    operator path back into that target without filing a new moderation
    decision: ``/tcrepair retry <run_id> [chat_id]`` makes the failed
    group due again and hands the existing run to the worker.
    """
    msg = ctx.effective_message
    if msg is None:
        return
    locale = await locale_for_update(ctx)
    args = parse_cmd_args(msg.text)
    if not args:
        await _reply_repair_list(msg, locale)
        return
    if args[0].lower() != "retry" or len(args) > 3:
        await reply_rich(
            msg,
            t("maintenance.repair.usage", locale),
            log_label="tcrepair usage",
            parse_mode=None,
        )
        return
    if len(args) < 2:
        await reply_rich(
            msg,
            t("maintenance.repair.usage", locale),
            log_label="tcrepair usage",
            parse_mode=None,
        )
        return
    run_id = as_int(args[1])
    chat_id = as_int(args[2]) if len(args) == 3 else None
    if run_id <= 0 or (len(args) == 3 and chat_id in (None, 0)):
        await reply_rich(
            msg,
            t("maintenance.repair.usage", locale),
            log_label="tcrepair invalid",
            parse_mode=None,
        )
        return
    try:
        result = await db.enforcement_ledger.redrive_run(run_id, chat_id=chat_id)
    except Exception:
        log.exception("redrive_run failed for run=%d", run_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="tcrepair retry-failed",
            parse_mode=None,
        )
        return

    run_ref = Safe(code(str(run_id)))
    if result.state == "queued":
        # * Deliver now when this process can claim the run; a claim
        # * failure is not an error because the scheduled worker owns it.
        try:
            await moderation_enforcement.deliver_queued_run(ctx.bot, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Repair delivery failed for run=%d; it stays queued", run_id)
        await reply_rich(
            msg,
            t(
                "maintenance.repair.queued",
                locale,
                run=run_ref,
                n=result.targets,
            ),
            log_label=f"tcrepair queued run {run_id}",
        )
        return
    key = {
        "no_failed_target": "maintenance.repair.no_failed",
        "in_progress": "maintenance.repair.in_progress",
        "cancelled": "maintenance.repair.cancelled",
        "missing": "maintenance.repair.missing",
    }.get(result.state)
    await reply_rich(
        msg,
        t(key or "maintenance.repair.missing", locale, run=run_ref),
        log_label=f"tcrepair {result.state} run {run_id}",
    )


# ────────────────── Command Forget </tcforget> ────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_FEDERATION)
@decorators.owner_only
@decorators.log_execution
async def cmd_forget(ctx: Ctx) -> None:
    """Queue one Telegram-account erasure for the next cleanup sweep."""
    msg = ctx.effective_message
    if msg is None:
        return
    locale = await locale_for_update(ctx)
    args = parse_cmd_args(msg.text)
    if len(args) < 2:
        await reply_rich(
            msg,
            t("maintenance.forget.usage", locale),
            log_label="tcforget usage",
            parse_mode=None,
        )
        return
    try:
        user_id = int(args[0])
    except ValueError:
        user_id = 0
    reason = " ".join(args[1:]).strip()
    if user_id <= 0 or not reason:
        await reply_rich(
            msg,
            t("maintenance.forget.usage", locale),
            log_label="tcforget invalid",
            parse_mode=None,
        )
        return
    try:
        owner_id = await db.users_roles.get_owner_id(fresh=True)
    except Exception:
        log.exception("tcforget owner lookup failed")
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="tcforget owner-lookup-failed",
            parse_mode=None,
        )
        return
    if owner_id == user_id:
        # ! CRITICAL: erasing the Owner would revoke the only owner row,
        # ! and the boot seed could recreate it for the erased account. The
        # ! operator must transfer ownership before erasing that account.
        await reply_rich(
            msg,
            t("maintenance.forget.owner", locale, plain=True),
            log_label="tcforget current-owner",
            parse_mode=None,
        )
        return
    try:
        request_id = await db.erasure_db.request_erasure(user_id, reason)
    except Exception:
        log.exception("tcforget request failed for user=%d", user_id)
        await reply_rich(
            msg,
            t("maintenance.forget.failed", locale, plain=True),
            log_label="tcforget failed",
            parse_mode=None,
        )
        return
    await reply_rich(
        msg,
        t(
            "maintenance.forget.queued",
            locale,
            user=Safe(code(str(user_id))),
            request=Safe(code(str(request_id))),
        ),
        log_label=f"tcforget queued for {user_id}",
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_LEAVEALL_CMDS = (
    build_prefixed_filters("leaveall")
    | build_prefixed_filters("exitall")
    | build_prefixed_filters("tcleave")
)
_CLEANUP_CMDS = (
    build_prefixed_filters("cleanup")
    | build_prefixed_filters("tcclean")
    | build_prefixed_filters("tcc")
)
_FORGET_CMDS = build_prefixed_filters("tcforget") | build_prefixed_filters("tcf")
_REPAIR_CMDS = build_prefixed_filters("tcrepair") | build_prefixed_filters("tcr")


__handlers__ = [
    MessageHandler(_LEAVEALL_CMDS, cmd_leaveall),
    MessageHandler(_CLEANUP_CMDS, cmd_cleanup),
    MessageHandler(_REPAIR_CMDS, cmd_repair),
    MessageHandler(_FORGET_CMDS, cmd_forget),
]
