# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warning actor, threshold ban, management, and conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Message, Update

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, keyboards, messages
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_reply, send_log
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.proof_flow import (
    BuildProof,
    ProofUpload,
    upload_proof_for_action,
)
from tcbot.modules.helper.pipelines.reason_flow import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")

# ────────────────────────── Warn executor ───────────────────────── #


async def execute_warn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_msgs: list[Message] | None = None,
) -> None:
    """Issue a warning and ban the target if a warn threshold is reached."""
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    admin = update.effective_user
    if admin is None:
        return
    admin_id = admin.id
    admin_fname = admin.first_name
    locale = await locale_for_update(update)
    warn_limit = cfg.warn_limit
    # * Re-check the executor against the target before anything is
    # * recorded or uploaded. The entry command compared the two roles,
    # * but the proof window can stay open for a minute, and a target
    # * promoted in that window must not be warned by a moderator who no
    # * longer outranks them. The check runs first so a refused warning
    # * leaves no record, no counter, no demotion, and no orphan proof.
    verdict, target_label = await decorators.enforcement_verdict(admin_id, target_id)
    if verdict is not decorators.EnforcementVerdict.ALLOWED:
        log.warning(
            "Warn refused for target=%d: executor=%d (%s)",
            target_id,
            admin_id,
            verdict.value,
        )
        await safe_reply(
            msg,
            (
                replies.refuse_outranked(target_label or "", locale, plain=True)
                if verdict is decorators.EnforcementVerdict.OUTRANKED
                else replies.refuse_role_lookup(locale, plain=True)
            ),
            log_label="execute_warn rank-refusal",
            parse_mode=None,
        )
        return
    proof_task: asyncio.Task[ProofUpload] | None = None
    if proof_msgs:
        proof_task = asyncio.create_task(
            upload_proof_for_action(
                ctx.bot, proof_msgs, target_id, admin_id, admin_fname
            )
        )
    try:
        count = await db.warns_db.add_warn(target_id, reason_text, admin_id, chat_id)
    except Exception:
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        log.exception(
            "add_warn DB write failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warn DB-fail",
            parse_mode=None,
        )
        return
    proof_link: str | None = None
    warn_proof_id: int | None = None
    if proof_task is not None:
        try:
            upload = await proof_task
        except asyncio.CancelledError:
            proof_task.cancel()
            raise
        except Exception:
            log.warning("Warn proof upload skipped for target=%d", target_id)
        else:
            warn_proof_id = upload.message_id
            proof_link = upload.link
    proof_kb = keyboards.action_proof_kb(target_id, proof_link)
    log_text = messages.warn_log(
        target_id,
        target_name,
        admin_id,
        admin_fname,
        reason_text,
        count,
        warn_limit,
        chat_id,
        chat_title,
    )
    threshold_trigger: str | None = None
    fed_count: int = 0
    if count >= warn_limit:
        threshold_trigger = "per_group"
    else:
        fed_limit = cfg.fed_warn_limit
        if fed_limit > 0:
            try:
                fed_count = await db.warns_db.federation_warn_count(target_id)
            except Exception:
                log.exception("federation_warn_count failed for target=%d", target_id)
                await safe_reply(
                    msg,
                    t(
                        "warnings.fed_fail.body",
                        locale,
                        user=Safe(user_ref(target_id, target_name)),
                        count=count,
                        limit=warn_limit,
                        reason=reason_text,
                    ),
                    log_label="execute_warn fed-count-fail",
                    reply_markup=proof_kb,
                )
                return
            if fed_count >= fed_limit:
                threshold_trigger = "fed_global"
    if threshold_trigger is not None:
        fed_warn_limit = cfg.fed_warn_limit
        try:
            target_role = await db.users_roles.get_effective_role(target_id, fresh=True)
        except Exception:
            log.exception(
                "Warn threshold ban role lookup failed for target=%d; aborting threshold ban",
                target_id,
            )
            await safe_reply(
                msg,
                replies.err_db_retry(locale, plain=True),
                log_label="Warn threshold lookup-fail",
                parse_mode=None,
            )
            return
        # * Staff are exempt from warn threshold ban; demoted first so rank never survives.
        if target_role:
            demoted = False
            try:
                # * The return value is the source of truth: a role that was
                # * already gone is a no-op, and reporting it as a demotion
                # * would tell the moderator a rank was removed when it
                # * was not.
                demoted = await Demote.execute(
                    ctx.bot,
                    target_id,
                    target_name,
                    target_role,
                    admin_id,
                    admin_fname,
                    trigger="ban",
                )
            except Exception:
                demoted = False
                log.exception("Demote on warn limit failed for role=%s", target_role)
            exemption_text = (
                t(
                    "warnings.exempt.demoted",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    role=target_role,
                )
                if demoted
                else t(
                    "warnings.exempt.failed",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    role=target_role,
                )
            )
            await safe_reply(
                msg,
                exemption_text,
                log_label="Warn threshold staff exemption",
                reply_markup=proof_kb,
            )
            return
        groups_result, existing_ban = await asyncio.gather(
            db.groups_db.active_groups(),
            db.bans_db.get_active_ban(target_id),
            return_exceptions=True,
        )
        throw_if_cancelled((groups_result, existing_ban))
        groups_fetch_failed = isinstance(groups_result, BaseException)
        if groups_fetch_failed:
            log.exception(
                "Warn threshold ban groups fetch failed for target=%d; enforcing reduced scope",
                target_id,
            )
        groups: list = [] if groups_fetch_failed else groups_result
        already_banned = (
            not isinstance(existing_ban, BaseException) and existing_ban is not None
        )
        groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,), chat_id)
        ban_id: str | None = None
        if not already_banned:
            try:
                ban_doc = await db.bans_db.create_ban(
                    target_id, reason_text, admin_id, warn_proof_id or 0, 0
                )
                ban_id = ban_doc.get("ban_id", "")
            except Exception:
                log.exception(
                    "Failed to create federation ban record on warn limit for user %d",
                    target_id,
                )
                await safe_reply(
                    msg,
                    t(
                        "warnings.autoban.db_fail",
                        locale,
                        user=Safe(user_ref(target_id, target_name)),
                    ),
                    log_label="Warn threshold DB-fail",
                    reply_markup=proof_kb,
                )
                return
            # * Two moderators hitting the threshold at the same moment can
            # * insert two active records; converge on the canonical one so
            # * /check and the appeal deep link agree on the same ban.
            try:
                extras = await db.bans_db.deactivate_extra_active_bans(
                    target_id, ban_id
                )
            except Exception:
                log.exception(
                    "Duplicate active ban cleanup failed for user %d", target_id
                )
            else:
                if extras > 0:
                    log.warning(
                        "Suppressed %d duplicate active ban(s) for user %d after "
                        "warn-threshold ban",
                        extras,
                        target_id,
                    )
        try:
            log_msg = await send_log(
                ctx.bot,
                log_text,
                reply_markup=proof_kb,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Warn threshold log send failed")
            log_msg = None
        if ban_id and log_msg is not None:
            try:
                await db.bans_db.set_log_message_id(ban_id, log_msg.message_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Warn threshold set_log_message_id failed")
        ban_results = await fan_out(
            [ctx.bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
        )
        outcome = summarize_fanout(
            groups, ban_results, action="Warn threshold ban", target_id=target_id
        )
        total_groups = outcome.total
        applied = outcome.applied
        any_ban_ok = applied > 0
        log.info(
            "Warn threshold ban enforced (%s): target=%d applied=%d/%d",
            threshold_trigger,
            target_id,
            applied,
            total_groups,
        )
        applied_line = replies.applied_summary(
            locale,
            "warnings.autoban",
            total=total_groups,
            failed=outcome.failed,
            transient=outcome.transient,
        )
        if groups_fetch_failed:
            applied_line += t("warnings.autoban.scope_warn", locale)
        if threshold_trigger == "per_group":
            ban_notice = t(
                "warnings.autoban.notice_per_group",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                limit=warn_limit,
            )
            ban_fail_notice = t(
                "warnings.autoban.fail_per_group",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                limit=warn_limit,
            )
        else:
            ban_notice = t(
                "warnings.autoban.notice_fed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                fed=fed_count,
                fedlimit=fed_warn_limit,
            )
            ban_fail_notice = t(
                "warnings.autoban.fail_fed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                fed=fed_count,
                fedlimit=fed_warn_limit,
            )
        if any_ban_ok:
            # * The reply is best-effort: a failed notification must not
            # * skip the warn cleanup below.
            try:
                await msg.reply_text(
                    f"{ban_notice}{applied_line}",
                    parse_mode="MarkdownV2",
                    reply_markup=proof_kb,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("Threshold ban notification reply failed: %s", exc)
            # * The warn slate is cleared only where the ban actually landed.
            # * Clearing everything after a partial enforcement left the
            # * failed groups with no warning and no ban, so their threshold
            # * could never fire again. A complete enforcement clears the
            # * whole slate so a later unban does not re-ban on stale counts.
            clear_result = await _clear_warns_after_threshold_ban(
                target_id, groups, ban_results
            )
            if isinstance(clear_result, BaseException):
                log.error(
                    "Warn clear after threshold ban failed for target=%d chat=%d: %s",
                    target_id,
                    chat_id,
                    clear_result,
                )
        else:
            await safe_reply(
                msg,
                f"{ban_fail_notice}{applied_line}",
                log_label="Threshold ban failure notice",
                reply_markup=proof_kb,
            )
        return
    results2 = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
            reply_markup=proof_kb,
        ),
        msg.reply_text(
            t(
                "warnings.issued.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                count=count,
                limit=warn_limit,
                reason=reason_text,
            ),
            parse_mode="MarkdownV2",
            reply_markup=proof_kb,
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results2)
    if isinstance(results2[0], BaseException):
        log.error("Warn log send failed: %s", results2[0])


# ───────────────────────── Warn management ──────────────────────── #


async def _clear_warns_after_threshold_ban(
    target_id: int,
    groups: list[dict[str, Any]],
    ban_results: list[Any],
) -> Any:
    """Clear the warn slate of the groups the threshold ban reached.

    A complete enforcement clears every group so a later unban does not
    re-ban on stale counts. A partial enforcement clears only the groups
    where the ban landed: the failed groups keep their warnings so their
    threshold can fire again once the enforcement succeeds.
    """
    failed = count_transient_errors(ban_results)
    if failed == 0:
        return await db.warns_db.clear_all_warns(target_id)
    landed = [
        int(grp["chat_id"])
        for grp, result in zip(groups, ban_results, strict=False)
        if not isinstance(result, BaseException)
    ]
    log.warning(
        "Warn threshold ban applied to %d/%d groups for target=%d; "
        "warnings kept in the groups where enforcement failed.",
        len(landed),
        len(groups),
        target_id,
    )
    return await db.warns_db.clear_warns_for_chats(target_id, landed)


async def execute_unwarn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Remove one warning from the target in the current group."""
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)
    try:
        count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count read failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn DB-fail",
            parse_mode=None,
        )
        return
    if count == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn no-warns",
        )
        return
    new_count = max(count - 1, 0)
    chat_title = chat.title or str(chat_id)
    warn_limit = cfg.warn_limit
    admin = update.effective_user
    if admin is None:
        return
    log_text = messages.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    try:
        removed = await db.warns_db.remove_last_warn(target_id, chat_id)
    except Exception:
        log.exception(
            "remove_last_warn DB write failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn db_retry",
            parse_mode=None,
        )
        return
    if not removed:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn empty",
        )
        return
    try:
        new_count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count re-read failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        new_count = max(count - 1, 0)
    log_text = messages.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        msg.reply_text(
            t(
                "warnings.removed.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                new=new_count,
                limit=warn_limit,
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    if isinstance(results[0], BaseException):
        log.error("Unwarn log send failed: %s", results[0])


async def execute_warnlist(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Reply with the numbered list of active warnings for the target."""
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)
    try:
        # * Cap the numbered render: a pathological history must not
        # * become an unbounded message. Total count stays honest via
        # * the header; the list shows the 50 most recent.
        warns = await db.warns_db.get_warns(
            target_id, chat_id, newest_first=True, limit=50
        )
    except Exception:
        log.exception("get_warns read failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warnlist DB-fail",
            parse_mode=None,
        )
        return
    try:
        total = await db.warns_db.warn_count(target_id, chat_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        total = len(warns)
    count = max(total, len(warns))
    if count == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_warnlist no-warns",
        )
        return
    header = t(
        "warnings.list.header",
        locale,
        user=Safe(user_ref(target_id, target_name)),
        count=count,
        limit=cfg.warn_limit,
    )
    lines = [header]
    for i, w in enumerate(warns, 1):
        lines.append(
            t(
                "warnings.list.item",
                locale,
                i=i,
                reason=w.get("reason", "")
                or t("warnings.list.no_reason", locale, plain=True),
            )
        )
    await safe_reply(msg, "\n".join(lines), log_label="execute_warnlist")


async def execute_resetwarns(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Clear all active warnings for the target in the current group."""
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    locale = await locale_for_update(update)
    removed = 0
    try:
        removed = await db.warns_db.clear_warns(target_id, chat_id)
    except Exception:
        log.exception("clear_warns failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_resetwarns DB-fail",
            parse_mode=None,
        )
        return
    if removed == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none_clear.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_resetwarns no-warns",
        )
        return
    log_text = messages.resetwarns_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        removed,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        msg.reply_text(
            t(
                "warnings.cleared.body",
                locale,
                removed=removed,
                user=Safe(user_ref(target_id, target_name)),
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    if isinstance(results[0], BaseException):
        log.exception(
            "Reset-warns log send failed for target=%d: %s", target_id, results[0]
        )


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop warn data from the conversation scope and call execute_warn."""
    if ctx.user_data is None:
        log.warning("_exec_warn called without user_data")
        return
    scope = flow_scope(ctx, update)
    target_id = scope.pop("warn_target_id", 0)
    target_name = scope.pop("warn_target_name", "")
    reason_text = scope.pop("warn_reason", "")
    proof_msgs = scope.pop("warn_proof_msgs", None)
    scope.pop("warn_extra_info", None)
    await execute_warn(
        update, ctx, target_id, target_name, reason_text, proof_msgs=proof_msgs
    )


# ─────────────────── ConversationHandler factory ────────────────── #


def warn_conversation(
    entry_fn: Callable[..., object],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the warn ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_warn,
        entry_filter,
        escape_filter=escape_filter,
        min_role="tester",
    )
