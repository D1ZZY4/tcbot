# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Ban executor + proof collection conversation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.formatter import esc, mention
from tcbot.modules.helper.parse_link import appeal_deep_link, message_link
from tcbot.modules.helper.workflows.proof_flow import BuildProof, upload_proof
from tcbot.utils.dispatch import count_errors, fan_out
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Bot, Message
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_MSG_CANCELLED = "Cancelled. No ban was issued."
_MSG_TIMEOUT = "Timed out waiting for proof. No ban was issued."
_MSG_PROOF_EXPECTED = "Please send a photo or video as proof, or press Cancel."

_BAN_USER_DATA_KEYS = (
    "ban_target_id",
    "ban_target_fname",
    "ban_reason",
    "ban_admin_id",
    "ban_admin_fname",
    "ban_prompt_msg_id",
    "ban_prompt_chat_id",
)

WAITING_PROOF = 0

# * Per-action BuildProof instance; imported by banning.py
# * skip_allowed=False: ban proof is required; there is no Skip option
proof = BuildProof("ban", skip_allowed=False)

# * Module-level album accumulators (keyed by media_group_id)
_albums: dict[str, list[Message]] = {}
_album_meta: dict[str, dict[str, Any]] = {}

# * Weak references to user_data dicts for post-flush cleanup (keyed by media_group_id).
# * Stored as a reference (not a copy) so we can clear ban keys after execution.
_album_userdata: dict[str, dict[str, Any]] = {}

# * Strong references to in-flight album flush tasks (prevents GC)
_album_tasks: set[asyncio.Task[None]] = set()


# ────────────────────────── Ban executor ────────────────────────── #


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id")
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    reason: str = meta.get("ban_reason", replies.NO_REASON)
    admin_id: int = meta.get("ban_admin_id")
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)

    now = utc_now()
    proof_chat, proof_thread = cfg.proofs

    # * Pre-fetch active groups immediately so DB round-trip overlaps with the
    # * get_active_ban call and the proof-upload I/O that follows.
    _groups_task: asyncio.Task[list] = asyncio.create_task(db.groups_db.active_groups())

    existing = await db.bans_db.get_active_ban(target_id)
    is_update = existing is not None

    # * Start old-admin name fetch immediately - runs during proof upload I/O below
    _old_admin_fname_task = (
        asyncio.create_task(
            db.users_cache.get_first_name(
                existing.get("admin_user_id", admin_id), "Admin"
            )
        )
        if is_update
        else None
    )

    # * Build proof caption
    if is_update:
        prev_proof_msg_id = existing.get("proof_message_id")
        prev_proof_link = (
            message_link(proof_chat, prev_proof_msg_id, proof_thread)
            if prev_proof_msg_id
            else None
        )
        caption = parse_logmsg.proof_caption_update(
            target_id,
            admin_id,
            admin_fname,
            existing.get("timestamp", now),
            prev_proof_link,
        )
    else:
        prev_proof_link = None
        caption = parse_logmsg.proof_caption_new(target_id, admin_id, admin_fname, now)

    # * Upload proof to PROOF channel
    proof_msg_id = await upload_proof(bot, msgs, caption, proof_chat, proof_thread)
    proof_link = (
        message_link(proof_chat, proof_msg_id, proof_thread) if proof_msg_id else None
    )

    logs_chat, logs_thread = cfg.logs

    if is_update:
        ban_id = existing["ban_id"]
        old_admin_id = existing.get("admin_user_id", admin_id)
        bot_username = bot.username or "TCFBot"
        old_admin_fname = await _old_admin_fname_task
        old_proof_msg_id = existing.get("proof_message_id", 0)
        old_log_msg_id = existing.get("log_message_id", 0)
        new_proof_msg_id = proof_msg_id or old_proof_msg_id

        log_text = parse_logmsg.ban_update_log(
            target_id,
            target_fname,
            admin_id,
            admin_fname,
            old_admin_id,
            old_admin_fname,
            reason,
            ban_id,
            existing.get("timestamp", now),
            proof_link,
            prev_proof_link,
        )
        _appeal_url = appeal_deep_link(bot_username, ban_id)
        kb = (
            keyboards.ban_log_update(
                target_id,
                proof_link,
                prev_proof_link,
                _appeal_url,
            )
            if proof_link and prev_proof_link
            else (
                keyboards.ban_log_new(target_id, proof_link, _appeal_url)
                if proof_link
                else None
            )
        )

        send_kwargs: dict = {"parse_mode": "HTML", "message_thread_id": logs_thread}
        if kb:
            send_kwargs["reply_markup"] = kb
        db_result, log_result = await asyncio.gather(
            db.bans_db.update_ban(
                ban_id,
                reason,
                admin_id,
                new_proof_msg_id,
                old_log_msg_id,
                old_proof_msg_id,
                old_log_msg_id,
            ),
            bot.send_message(logs_chat, log_text, **send_kwargs),
            return_exceptions=True,
        )
        if isinstance(db_result, BaseException):
            log.error("update_ban failed for ban_id=%s: %s", ban_id, db_result)
    else:
        ban_id = db.bans_db.make_ban_id()
        bot_username = bot.username or "TCFBot"

        log_text = parse_logmsg.ban_log(
            target_id,
            target_fname,
            admin_id,
            admin_fname,
            reason,
            ban_id,
            proof_link,
            now,
        )
        kb = (
            keyboards.ban_log_new(
                target_id,
                proof_link,
                appeal_deep_link(bot_username, ban_id),
            )
            if proof_link
            else None
        )

        send_kwargs = {"parse_mode": "HTML", "message_thread_id": logs_thread}
        if kb:
            send_kwargs["reply_markup"] = kb
        db_result, log_result = await asyncio.gather(
            db.bans_db.create_ban(
                target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id
            ),
            bot.send_message(logs_chat, log_text, **send_kwargs),
            return_exceptions=True,
        )
        if isinstance(db_result, BaseException):
            log.error("create_ban failed for ban_id=%s: %s", ban_id, db_result)

    # * Extract log_msg_id from parallel result
    log_msg_id: int = 0
    if not isinstance(log_result, BaseException):
        log_msg_id = log_result.message_id
        log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    else:
        log.error("Ban log send failed: %s", log_result)

    # * set_log_message_id and pre-fetched active_groups in parallel.
    # * _groups_task was started at the top of this function and has been
    # * running concurrently through get_active_ban, upload_proof, and log send.
    if log_msg_id:
        set_log_result, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            _groups_task,
            return_exceptions=True,
        )
        if isinstance(set_log_result, BaseException):
            log.error(
                "set_log_message_id failed for ban_id=%s: %s", ban_id, set_log_result
            )
        if isinstance(groups, BaseException):
            log.error("active_groups failed during ban of %d: %s", target_id, groups)
            groups = []
    else:
        try:
            groups = await _groups_task
        except Exception:
            log.exception("active_groups failed during ban of %d", target_id)
            groups = []

    # * Enforce across all connected groups - semaphore-bounded for rate safety
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    failed = count_errors(results)
    log.info(
        "Ban enforced: target=%s groups=%d/%d",
        target_id,
        len(groups) - failed,
        len(groups),
    )

    # * Edit the original prompt to a summary + cache user in parallel
    summary = (
        f"{mention(target_id, target_fname)} - <code>{target_id}</code> has been banned.\n"
        f"Reason: {esc(reason)}\n"
        f"Applied to {len(groups) - failed}/{len(groups)} groups."
    )
    if prompt_msg_id and prompt_chat_id:
        _, upsert_result = await asyncio.gather(
            bot.edit_message_text(
                summary,
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                parse_mode="HTML",
                reply_markup=None,
            ),
            db.users_cache.upsert_user(target_id, None, target_fname),
            return_exceptions=True,
        )
        if isinstance(upsert_result, BaseException):
            log.error("upsert_user failed for target=%d: %s", target_id, upsert_result)
    else:
        await db.users_cache.upsert_user(target_id, None, target_fname)


# ───────────────── Proof collection state handlers ──────────────── #


async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle incoming proof media: buffer albums or execute the ban immediately."""
    msg = update.effective_message
    if msg is None:
        return WAITING_PROOF

    if msg.media_group_id:
        mgid = msg.media_group_id
        if mgid not in _albums:
            _albums[mgid] = []
            _album_meta[mgid] = dict(ctx.user_data)
            _album_userdata[mgid] = ctx.user_data
            task = asyncio.create_task(_flush_album(mgid, ctx.bot))
            _album_tasks.add(task)
            task.add_done_callback(_album_tasks.discard)
        _albums[mgid].append(msg)
        return WAITING_PROOF

    # * Single media file - execute immediately
    await _execute_ban(ctx.bot, [msg], dict(ctx.user_data))
    return ConversationHandler.END


async def _flush_album(mgid: str, bot: Bot) -> None:
    await asyncio.sleep(cfg.album_debounce)
    msgs = _albums.pop(mgid, [])
    meta = _album_meta.pop(mgid, {})
    user_data = _album_userdata.pop(mgid, None)
    if not msgs or not meta:
        return
    if not meta.get("ban_target_id") or not meta.get("ban_admin_id"):
        log.warning(
            "Album flush aborted for %s: meta missing target_id or admin_id", mgid
        )
        return
    log.info("Flushing album %s with %d media items", mgid, len(msgs))
    await _execute_ban(bot, msgs, meta)
    # * Clear ban keys from the live user_data so the ConversationHandler does
    # * not re-fire _execute_ban if a second album arrives before the conversation
    # * naturally times out or ends.
    if user_data is not None:
        for key in _BAN_USER_DATA_KEYS:
            user_data.pop(key, None)


async def on_proof_unexpected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unexpected message types during proof collection."""
    if update.effective_message:
        await update.effective_message.reply_text(_MSG_PROOF_EXPECTED)
    return WAITING_PROOF


async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Acknowledge the cancel button and end the proof-collection conversation."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END

    if ctx.user_data is not None:
        for key in _BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)

    await asyncio.gather(
        q.answer(), q.edit_message_text(_MSG_CANCELLED), return_exceptions=True
    )
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Notify the user that the proof window expired and end the conversation."""
    if ctx.user_data is not None:
        for key in _BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)

    if update.effective_message:
        await update.effective_message.reply_text(_MSG_TIMEOUT)
    return ConversationHandler.END


# ─────────────────── ConversationHandler factory ────────────────── #


def ban_conversation(
    entry_fn: Callable[..., Any], entry_filter: BaseFilter
) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function."""
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
                MessageHandler(
                    ~filters.PHOTO & ~filters.VIDEO & ~ALL_PREFIXES_CMD_FILTER,
                    on_proof_unexpected,
                ),
            ],
            ConversationHandler.TIMEOUT: [TypeHandler(Update, on_proof_timeout)],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER, on_proof_timeout)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
