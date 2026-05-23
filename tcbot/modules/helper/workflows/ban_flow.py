# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Ban executor + proof collection conversation

Sections
────────
proof             — BuildProof instance for the ban action (skip_allowed=False)
_execute_ban()    — federation-wide ban, DB write, log dispatch, group enforcement
on_proof_received() — WAITING_PROOF handler — single or album proof
on_cancel_proof() — cancel callback
on_proof_timeout() — timeout / fallback handler
ban_conversation() — ConversationHandler factory
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import appeal_deep_link, message_link
from tcbot.modules.helper.workflows.proof_flow import BuildProof, upload_proof
from tcbot.utils.dispatch import fan_out
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.timedate_format import utc_now

log = logging.getLogger(__name__)

WAITING_PROOF = 0

# * Per-action BuildProof instance — imported by banning.py
# * skip_allowed=False: ban proof is required; there is no Skip option
proof = BuildProof("ban", skip_allowed=False)

# * Module-level album accumulators (keyed by media_group_id)
_albums: dict[str, list[Message]] = {}
_album_meta: dict[str, dict[str, Any]] = {}


# ── Ban executor ────────────────────────────────────────────────────────────


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id")
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    reason: str = meta.get("ban_reason", "No reason provided")
    admin_id: int = meta.get("ban_admin_id")
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)

    now = utc_now()
    proof_chat, proof_thread = cfg.proofs

    existing = await db.bans_db.get_active_ban(target_id)
    is_update = existing is not None

    # * Start old-admin name fetch immediately - runs during proof upload I/O below
    _old_admin_fname_task = (
        asyncio.create_task(
            db.users_db.get_first_name(existing.get("admin_user_id", admin_id), "Admin")
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
        _, log_result = await asyncio.gather(
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
        _, log_result = await asyncio.gather(
            db.bans_db.create_ban(
                target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id
            ),
            bot.send_message(logs_chat, log_text, **send_kwargs),
            return_exceptions=True,
        )

    # * Extract log_msg_id from parallel result
    log_msg_id: int = 0
    if not isinstance(log_result, BaseException):
        log_msg_id = log_result.message_id
        log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    else:
        log.error("Ban log send failed: %s", log_result)

    # * set_log_message_id and active_groups fetched in parallel
    if log_msg_id:
        _, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            db.groups_db.active_groups(),
        )
    else:
        groups = await db.groups_db.active_groups()

    # * Enforce across all connected groups - semaphore-bounded for rate safety
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    failed = sum(1 for r in results if isinstance(r, BaseException))
    log.info(
        "Ban enforced: target=%s groups=%d/%d",
        target_id,
        len(groups) - failed,
        len(groups),
    )

    # * Edit the original prompt to a summary + cache user in parallel
    summary = (
        f"{mention(target_id, target_fname)} (<code>{target_id}</code>) has been banned.\n"
        f"Reason: {reason}\n"
        f"Applied to {len(groups) - failed}/{len(groups)} groups."
    )
    if prompt_msg_id and prompt_chat_id:
        await asyncio.gather(
            bot.edit_message_text(
                summary,
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                parse_mode="HTML",
                reply_markup=None,
            ),
            db.users_db.upsert_user(target_id, None, target_fname),
            return_exceptions=True,
        )
    else:
        await db.users_db.upsert_user(target_id, None, target_fname)


# ── Proof collection state handlers ─────────────────────────────────────────


async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message

    if msg.media_group_id:
        mgid = msg.media_group_id
        if mgid not in _albums:
            _albums[mgid] = []
            _album_meta[mgid] = dict(ctx.user_data)
            asyncio.create_task(_flush_album(mgid, ctx.bot))
        _albums[mgid].append(msg)
        return WAITING_PROOF

    # * Single media file - execute immediately
    await _execute_ban(ctx.bot, [msg], dict(ctx.user_data))
    return ConversationHandler.END


async def _flush_album(mgid: str, bot: Bot) -> None:
    await asyncio.sleep(cfg.album_debounce)
    msgs = _albums.pop(mgid, [])
    meta = _album_meta.pop(mgid, {})
    if not msgs or not meta:
        return
    log.info("Flushing album %s with %d media items", mgid, len(msgs))
    await _execute_ban(bot, msgs, meta)


async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Cancelled. No ban was issued."),
    )
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Timed out waiting for proof. No ban was issued."
        )
    return ConversationHandler.END


# ── ConversationHandler factory ─────────────────────────────────────────────


def ban_conversation(entry_fn, entry_filter) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function."""
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
            ],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER, on_proof_timeout)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
