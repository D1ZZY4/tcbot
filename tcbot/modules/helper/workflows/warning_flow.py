# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Warning executor + conversation factory."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import esc, proof_line, user_ref
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason, build_modaction_conv
from tcbot.utils.dispatch import fan_out

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

WARN_LIMIT = 3

# * Per-action BuildReason and BuildProof instances; imported by warnings.py
# * skip_allowed=False because warn requires a reason; Skip is not offered
reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")


# ──────────────────────────── Executors ─────────────────────────── #


async def execute_warn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_desc: str | None = None,
) -> None:
    """Issue a warning and auto-ban the target if the warn limit is reached.

    Increments the warn counter via ``db.warns_db.add_warn``. If the new count
    meets or exceeds ``WARN_LIMIT``, any held federation role is demoted first,
    then the user is banned from the originating group and their warning record
    is cleared. Logs and user-facing replies always run in parallel via
    ``asyncio.gather``.
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    proof_suffix = proof_line(proof_desc)
    chat_title = update.effective_chat.title or str(chat_id)
    admin_fname = update.effective_user.first_name
    lc, lt = cfg.logs

    count = await db.warns_db.add_warn(target_id, reason_text, admin_id, chat_id)
    log_text = parse_logmsg.warn_log(
        target_id,
        target_name,
        admin_id,
        admin_fname,
        reason_text,
        count,
        WARN_LIMIT,
        chat_id,
        chat_title,
    )

    if count >= WARN_LIMIT:
        # * If the target somehow holds a federation role (e.g. promoted mid-warn-cycle),
        # * remove the role before the auto-ban so they don't keep staff perms after exile.
        target_role = await db.users_roles.get_effective_role(target_id)
        if target_role:
            try:
                await Demote.execute(
                    ctx.bot,
                    target_id,
                    target_name,
                    target_role,
                    admin_id,
                    admin_fname,
                    trigger="ban",
                )
            except Exception:
                log.exception("Auto-demote on warn limit failed")

        # * Federation ban: fetch active groups + check existing ban + send log in parallel.
        # * Overlapping the DB reads with the log send keeps total latency low.
        groups_result, existing_ban, log_result = await asyncio.gather(
            db.groups_db.active_groups(),
            db.bans_db.get_active_ban(target_id),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            return_exceptions=True,
        )
        if isinstance(log_result, BaseException):
            log.error("Warn-auto-ban log send failed: %s", log_result)
        log_msg_id: int = (
            log_result.message_id if not isinstance(log_result, BaseException) else 0
        )
        groups: list = (
            groups_result if not isinstance(groups_result, BaseException) else []
        )
        already_banned = (
            not isinstance(existing_ban, BaseException) and existing_ban is not None
        )

        # * Ensure the originating chat and primary groups are included even if they
        # * are not in federated_groups (primary groups are env-var-configured only).
        _all_group_ids: set[int] = {grp["chat_id"] for grp in groups}
        for _extra in [chat_id] + [
            cid for cid in (cfg.main_group, cfg.exec_group) if cid
        ]:
            if _extra not in _all_group_ids:
                groups = [*groups, {"chat_id": _extra}]
                _all_group_ids.add(_extra)

        # * Create DB ban record only when the user is not already federation-banned.
        # * proof_msg_id=0 because warn auto-bans have no uploaded proof media.
        if not already_banned:
            try:
                await db.bans_db.create_ban(
                    target_id, reason_text, admin_id, 0, log_msg_id
                )
            except Exception:
                log.exception(
                    "Failed to create federation ban record on warn limit for user %d",
                    target_id,
                )

        # * Fan-out ban to all federation groups concurrently (rate-limited by fan_out).
        ban_results = await fan_out(
            [ctx.bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
        )
        any_ban_ok = any(not isinstance(r, BaseException) for r in ban_results)

        if any_ban_ok:
            # * Clear warns in the originating chat and reply with federation-ban notice.
            clear_result, reply_result = await asyncio.gather(
                db.warns_db.clear_warns(target_id, chat_id),
                msg.reply_text(
                    f"{user_ref(target_id, target_name)} "
                    f"hit {WARN_LIMIT} warnings "
                    f"and has been federation-banned.{proof_suffix}",
                    parse_mode="HTML",
                ),
                return_exceptions=True,
            )
            if isinstance(clear_result, BaseException):
                log.error(
                    "Warn clear after auto-ban failed for target=%d chat=%d: %s",
                    target_id,
                    chat_id,
                    clear_result,
                )
            if isinstance(reply_result, BaseException):
                log.debug("Auto-ban notification reply failed: %s", reply_result)
        else:
            log.error(
                "All group bans failed on warn limit for target=%d; %d group(s) tried",
                target_id,
                len(groups),
            )
            try:
                await msg.reply_text(
                    f"{user_ref(target_id, target_name)} "
                    f"hit {WARN_LIMIT} warnings "
                    f"but federation-ban failed - please ban them manually.{proof_suffix}",
                    parse_mode="HTML",
                )
            except Exception as exc:
                log.debug("Auto-ban failure notice reply failed: %s", exc)
    else:
        # * federation log + reply in parallel
        results2 = await asyncio.gather(
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            msg.reply_text(
                f"{user_ref(target_id, target_name)} has been warned "
                f"({count}/{WARN_LIMIT}) - {esc(reason_text)}{proof_suffix}",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Warn log send failed: %s", results2[0])


async def execute_unwarn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Remove one warning from the target in the current group.

    Checks the current warn count; replies and returns early if the target has
    none. Otherwise decrements by one, logs the action, and sends the log and
    reply concurrently.
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    count = await db.warns_db.warn_count(target_id, chat_id)
    if count == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings in this group.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_unwarn no-warns reply failed: %s", exc)
        return

    new_count = max(count - 1, 0)
    chat_title = update.effective_chat.title or str(chat_id)
    admin = update.effective_user
    lc, lt = cfg.logs
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        WARN_LIMIT,
        chat_id,
        chat_title,
    )
    # * remove warn + send log + reply in parallel
    results = await asyncio.gather(
        db.warns_db.remove_last_warn(target_id, chat_id),
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"One warning removed from {user_ref(target_id, target_name)}. "
            f"They're now at {new_count}/{WARN_LIMIT}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error(
            "remove_last_warn DB write failed for target=%d chat=%d: %s",
            target_id,
            chat_id,
            results[0],
        )
    if isinstance(results[1], BaseException):
        log.error("Unwarn log send failed: %s", results[1])


async def execute_warnlist(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Reply with the numbered list of active warnings for the target in this group.

    Fetches all warnings from ``db.warns_db.get_warns`` and replies with a
    formatted list. Replies early if no warnings exist.
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    warns = await db.warns_db.get_warns(target_id, chat_id)
    count = len(warns)

    if count == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings in this group.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_warnlist no-warns reply failed: %s", exc)
        return

    lines = [f"{user_ref(target_id, target_name)} has {count}/{WARN_LIMIT} warnings:\n"]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {esc(w.get('reason', 'No reason'))}")

    try:
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as exc:
        log.debug("execute_warnlist reply failed: %s", exc)


async def execute_resetwarns(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Clear all active warnings for the target in the current group.

    Calls ``db.warns_db.clear_warns`` and replies with the number of removed
    warnings. Replies early if the target has no warnings to clear.
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    removed = await db.warns_db.clear_warns(target_id, chat_id)
    if removed == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings to clear.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_resetwarns no-warns reply failed: %s", exc)
        return

    try:
        await msg.reply_text(
            f"All {removed} warning(s) cleared for {user_ref(target_id, target_name)}. Clean slate.",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.debug("execute_resetwarns success reply failed: %s", exc)


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop warn data from user_data and call execute_warn."""
    target_id = ctx.user_data.pop("warn_target_id", 0)
    target_name = ctx.user_data.pop("warn_target_name", "")
    reason_text = ctx.user_data.pop("warn_reason", "")
    proof_desc = ctx.user_data.pop("warn_proof_desc", None)
    ctx.user_data.pop("warn_extra_info", None)
    await execute_warn(
        update, ctx, target_id, target_name, reason_text, proof_desc=proof_desc
    )


# ─────────────────── ConversationHandler factory ────────────────── #


def warn_conversation(
    entry_fn: Callable[..., Any],
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
    )
