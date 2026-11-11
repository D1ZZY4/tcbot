# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute/unmute executor + conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import Bot, ChatPermissions, Update

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, messages
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    replies,
    safe_edit_message,
    safe_reply,
    send_log,
)
from tcbot.modules.helper.pipelines.demote_flow import demote_before_enforcement
from tcbot.modules.helper.pipelines.proof_flow import (
    BuildProof,
    upload_proof_for_action,
)
from tcbot.modules.helper.pipelines.reason_flow import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.formatter import bold, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_duration, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

reason = BuildReason("mute")
proof = BuildProof("mute")

# ────────────────────────── Mute executor ───────────────────────── #


async def _execute_mute(bot: Bot, update: Update, meta: dict[str, Any]) -> None:
    """Apply a federation-wide mute across all connected groups."""
    target_id = meta.get("mute_target_id")
    admin_id = meta.get("mute_admin_id")
    if not target_id or not admin_id:
        log.warning("_execute_mute called with incomplete mute state; aborting")
        return
    target_fname = meta.get("mute_target_fname") or str(target_id)
    locale = await locale_for_update(update)
    reason_text = meta.get("mute_reason") or replies.no_reason(locale, plain=True)
    duration: timedelta | None = meta.get("mute_duration")
    proof_msgs = meta.get("mute_proof_msgs")
    prompt_chat = meta.get("mute_prompt_chat")
    prompt_id = meta.get("mute_prompt_id")
    dur_str = fmt_duration(duration, locale)
    until = utc_now() + duration if duration else None
    perms = ChatPermissions(can_send_messages=False)
    duration_secs = int(duration.total_seconds()) if duration else None
    admin_fname = meta.get("mute_admin_fname", "Admin")
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        log.warning("_execute_mute called without effective_chat")
        return
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("_execute_mute: active_groups failed for target=%d", target_id)
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "muting.note.groups_fail",
                locale,
                user=Safe(user_ref(target_id, target_fname)),
            ),
            log_level="debug",
            log_label="_execute_mute groups-fail",
            catch_all=True,
        )
        return
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    active_r: BaseException | None = None
    # * Active record lands before fan-out: no group is touched on DB failure.
    try:
        await db.mutes_db.set_active_mute(target_id, until=until)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        active_r = exc
    log_r: BaseException | None = None
    if active_r is None:
        try:
            await db.mutes_db.log_mute(
                target_id,
                chat_id,
                reason_text,
                admin_id,
                duration_secs=duration_secs,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            log_r = exc
    if log_r is not None or active_r is not None:
        if active_r is None:
            try:
                await db.mutes_db.clear_active_mute(target_id)
            except asyncio.CancelledError:
                raise
            except BaseException:
                log.exception("Failed to delete active mute for %d", target_id)
        log.error(
            "_execute_mute: mute DB write failed for target=%d (log=%s active=%s)",
            target_id,
            log_r,
            active_r,
        )
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "muting.note.db_fail",
                locale,
                user=Safe(user_ref(target_id, target_fname)),
            ),
            log_level="debug",
            log_label="_execute_mute DB-fail",
            catch_all=True,
        )
        return
    await demote_before_enforcement(
        bot,
        target_id,
        target_fname,
        trigger="mute",
        executor_id=admin_id,
        executor_fname=admin_fname,
    )
    restrict_coros = [
        bot.restrict_chat_member(
            grp.get("chat_id", 0),
            target_id,
            permissions=perms,
            until_date=until,
        )
        for grp in groups
    ]
    proof_link: str | None = None
    if proof_msgs:
        fanout_results, upload_result = await asyncio.gather(
            fan_out(restrict_coros),
            upload_proof_for_action(bot, proof_msgs, target_id, admin_id, admin_fname),
            return_exceptions=True,
        )
        if isinstance(fanout_results, BaseException):
            raise fanout_results
        results = fanout_results
        throw_if_cancelled((upload_result,))
        if isinstance(upload_result, BaseException):
            log.warning("Mute proof upload skipped for target=%d", target_id)
        else:
            proof_link = upload_result.link
    else:
        results = await fan_out(restrict_coros)
    outcome = summarize_fanout(groups, results, action="Mute", target_id=target_id)
    proof_kb = keyboards.action_proof_kb(target_id, proof_link, locale)
    summary = t(
        "muting.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        dur=Safe(bold(dur_str)),
        reason=reason_text,
        done=outcome.applied,
        total=outcome.total,
    )
    log_text = messages.mute_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason_text,
        dur_str,
    )
    log_send_r, edit_r = await asyncio.gather(
        send_log(
            bot,
            log_text,
            reply_markup=proof_kb,
        ),
        bot.edit_message_text(
            summary,
            chat_id=prompt_chat,
            message_id=prompt_id,
            parse_mode="MarkdownV2",
            reply_markup=proof_kb,
        ),
        return_exceptions=True,
    )
    throw_if_cancelled((log_send_r, edit_r))
    if isinstance(log_send_r, BaseException):
        log.error("Mute log send failed: %s", log_send_r)
    if isinstance(edit_r, BaseException):
        msg = update.effective_message
        if msg:
            await safe_reply(
                msg, summary, log_label="Mute summary fallback", reply_markup=proof_kb
            )


# ───────────────────────── Unmute executor ──────────────────────── #


async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Restore full send permissions across all connected groups."""
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    locale = await locale_for_update(update)
    try:
        active_mute = await db.mutes_db.get_active_mute(target_id)
    except Exception:
        log.exception("get_active_mute failed for target=%d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute DB-fail",
            parse_mode=None,
        )
        return
    if active_mute is None:
        await safe_reply(
            msg,
            t(
                "muting.note.no_mute",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute no-mute",
        )
        return
    full_perms = ChatPermissions(
        can_send_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
    )
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during unmute of %d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute groups-fail",
            parse_mode=None,
        )
        return
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    results = await fan_out(
        [
            ctx.bot.restrict_chat_member(
                grp.get("chat_id", 0),
                target_id,
                permissions=full_perms,
            )
            for grp in groups
        ]
    )
    outcome = summarize_fanout(groups, results, action="Unmute", target_id=target_id)
    failed = outcome.failed
    if groups and failed >= outcome.total:
        await safe_reply(
            msg,
            t(
                "muting.note.unmute_failed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute total-fail",
        )
        return
    if failed > 0:
        # * Partial success: keep the DB record so /tcsync can re-drive
        # * the remaining muted chats. Clearing here would strand the
        # * user muted with no repair path (sync never unrestricts).
        await safe_reply(
            msg,
            t(
                "muting.note.unmute_failed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute partial-fail",
        )
        return
    logs_chat, _ = cfg.logs
    log_text = messages.unmute_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
    )
    reply = t(
        "muting.unmute.body",
        locale,
        user=Safe(user_ref(target_id, target_name)),
        done=len(groups) - failed,
        total=len(groups),
    )
    try:
        await db.mutes_db.clear_active_mute(target_id)
    except Exception:
        log.exception("clear_active_mute failed for target=%d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute clear-failed",
            parse_mode=None,
        )
        return
    if logs_chat:
        results2 = await asyncio.gather(
            send_log(
                ctx.bot,
                log_text,
            ),
            msg.reply_text(reply, parse_mode="MarkdownV2"),
            return_exceptions=True,
        )
        throw_if_cancelled(results2)
        if isinstance(results2[0], BaseException):
            log.error("Unmute log send failed: %s", results2[0])
        if isinstance(results2[1], BaseException):
            log.debug("execute_unmute reply failed: %s", results2[1])
    else:
        try:
            await msg.reply_text(reply, parse_mode="MarkdownV2")
        except Exception as exc:
            log.debug("execute_unmute no-log reply failed: %s", exc)


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Copy mute data from the conversation scope, clean up, then call _execute_mute."""
    meta: dict[str, Any] = {}
    if ctx.user_data is not None:
        scope = flow_scope(ctx, update)
        meta = {k: v for k, v in scope.items() if k.startswith("mute_")}
        for k in list(meta):
            scope.pop(k, None)
    await _execute_mute(ctx.bot, update, meta)


# ─────────────────── ConversationHandler factory ────────────────── #


def mute_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the mute ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_mute,
        entry_filter,
        escape_filter=escape_filter,
        min_role="tester",
    )
