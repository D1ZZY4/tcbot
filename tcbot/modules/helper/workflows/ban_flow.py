# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban conversation workflow – no confirm step, proof only, immediate execution."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot, InputMediaPhoto, InputMediaVideo, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import extraction, keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.timedate_format import utc_now

log = logging.getLogger(__name__)

WAITING_PROOF = 0

## Module-level album accumulators
_albums: dict[str, list[Message]] = {}
_album_meta: dict[str, dict[str, Any]] = {}


## ---------------------------------------------------------------------------
## Entry point
## ---------------------------------------------------------------------------

async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    admin = update.effective_user

    if not await db.admins_db.is_staff(admin.id):
        await msg.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    raw_args = parse_cmd_args(msg.text)

    if msg.reply_to_message:
        target_id, target_fname = await extraction.extract_target(update, [], ctx.bot)
        reason = " ".join(raw_args).strip()
    else:
        target_id, target_fname = await extraction.extract_target(update, raw_args, ctx.bot)
        reason = " ".join(raw_args[1:]).strip()

    if not target_id:
        await msg.reply_text("Cannot resolve target. Reply to a message or provide a user ID.")
        return ConversationHandler.END

    if not reason:
        await msg.reply_text("A reason is required. Usage: /tcban <target> <reason>")
        return ConversationHandler.END

    if target_id == admin.id:
        await msg.reply_text("You cannot ban yourself.")
        return ConversationHandler.END

    if await db.admins_db.is_owner(target_id):
        await msg.reply_text("The owner cannot be banned.")
        return ConversationHandler.END

    ctx.user_data["ban_target_id"] = target_id
    ctx.user_data["ban_target_fname"] = target_fname or str(target_id)
    ctx.user_data["ban_reason"] = reason
    ctx.user_data["ban_admin_id"] = admin.id
    ctx.user_data["ban_admin_fname"] = admin.first_name

    prompt = await msg.reply_text(
        "Please provide proof for this ban. Send a photo or video (multiple media allowed). "
        f"You have {cfg.proof_timeout} seconds.",
        reply_markup=keyboards.cancel_proof_kb(),
    )
    ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
    ctx.user_data["ban_prompt_chat_id"] = msg.chat.id

    return WAITING_PROOF


## ---------------------------------------------------------------------------
## Proof received
## ---------------------------------------------------------------------------

async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    uid = update.effective_user.id

    if not await db.admins_db.is_staff(uid):
        return WAITING_PROOF

    if msg.media_group_id:
        mgid = msg.media_group_id
        if mgid not in _albums:
            _albums[mgid] = []
            _album_meta[mgid] = dict(ctx.user_data)
            asyncio.create_task(_flush_album(mgid, ctx.bot))
        _albums[mgid].append(msg)
        return WAITING_PROOF

    ## Single media – execute immediately
    await _execute_ban(ctx.bot, [msg], dict(ctx.user_data))
    return ConversationHandler.END


async def _flush_album(mgid: str, bot: Bot) -> None:
    await asyncio.sleep(cfg.album_debounce)
    msgs = _albums.pop(mgid, [])
    meta = _album_meta.pop(mgid, {})
    if not msgs or not meta:
        return
    await _execute_ban(bot, msgs, meta)


## ---------------------------------------------------------------------------
## Cancel callback
## ---------------------------------------------------------------------------

async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Operation cancelled.")
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Core ban execution
## ---------------------------------------------------------------------------

async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict) -> None:
    target_id: int = meta.get("ban_target_id")
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    reason: str = meta.get("ban_reason", "No reason provided")
    admin_id: int = meta.get("ban_admin_id")
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)

    now = utc_now()
    proof_chat, proof_thread = cfg.proofs

    ## Determine new vs update
    existing = await db.bans_db.get_active_ban(target_id)
    is_update = existing is not None

    ## Build proof caption
    if is_update:
        prev_proof_msg_id = existing.get("proof_message_id")
        prev_proof_link = (
            message_link(proof_chat, prev_proof_msg_id, proof_thread)
            if prev_proof_msg_id else None
        )
        caption = parse_logmsg.proof_caption_update(
            target_id, admin_id, admin_fname,
            existing.get("timestamp", now), prev_proof_link,
        )
    else:
        prev_proof_link = None
        caption = parse_logmsg.proof_caption_new(target_id, admin_id, admin_fname, now)

    ## Upload proof to PROOF topic
    proof_msg_id: int | None = None
    try:
        if len(msgs) > 1:
            media = []
            first_caption_set = False
            for m in msgs:
                if m.photo:
                    cap = caption if not first_caption_set else None
                    media.append(InputMediaPhoto(m.photo[-1].file_id, caption=cap, parse_mode="HTML"))
                    first_caption_set = True
                elif m.video:
                    cap = caption if not first_caption_set else None
                    media.append(InputMediaVideo(m.video.file_id, caption=cap, parse_mode="HTML"))
                    first_caption_set = True
            sent = await bot.send_media_group(proof_chat, media, message_thread_id=proof_thread)
            proof_msg_id = sent[0].message_id
        elif msgs[0].photo:
            sent = await bot.send_photo(
                proof_chat, msgs[0].photo[-1].file_id,
                caption=caption, parse_mode="HTML",
                message_thread_id=proof_thread,
            )
            proof_msg_id = sent.message_id
        elif msgs[0].video:
            sent = await bot.send_video(
                proof_chat, msgs[0].video.file_id,
                caption=caption, parse_mode="HTML",
                message_thread_id=proof_thread,
            )
            proof_msg_id = sent.message_id
    except Exception as exc:
        log.error("Proof upload failed: %s", exc)

    proof_link = (
        message_link(proof_chat, proof_msg_id, proof_thread) if proof_msg_id else None
    )

    ## Get bot username for appeal deep link
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = "TCFBot"

    logs_chat, logs_thread = cfg.logs

    if is_update:
        ban_id = existing["ban_id"]
        old_admin_id = existing.get("admin_user_id", admin_id)
        old_admin_fname = await db.users_db.get_first_name(old_admin_id, "Admin")
        log_text = parse_logmsg.ban_update_log(
            target_id, target_fname,
            admin_id, admin_fname,
            old_admin_id, old_admin_fname,
            reason, ban_id,
            existing.get("timestamp", now),
            proof_link, prev_proof_link,
        )
        kb = keyboards.ban_log_update_kb(
            target_id, proof_link or "#", prev_proof_link or "#",
            bot_username, ban_id,
        ) if proof_link and prev_proof_link else (
            keyboards.ban_log_kb(target_id, proof_link or "#", bot_username, ban_id)
            if proof_link else None
        )
        ## Update DB record
        await db.bans_db.update_ban(
            ban_id, reason, admin_id,
            proof_msg_id or 0, 0,
            existing.get("proof_message_id", 0),
            existing.get("log_message_id", 0),
        )
    else:
        ## Pre-generate ban_id so we can use it in the log keyboard
        ban_id = db.bans_db.make_ban_id(target_id)
        log_text = parse_logmsg.ban_log(
            target_id, target_fname, admin_id, admin_fname,
            reason, ban_id, proof_link, now,
        )
        kb = keyboards.ban_log_kb(
            target_id, proof_link or "#", bot_username, ban_id,
        ) if proof_link else None
        await db.bans_db.create_ban(target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id)

    ## Send log message to LOG_CHANNEL
    log_msg_id: int = 0
    try:
        send_kwargs: dict = {"parse_mode": "HTML", "message_thread_id": logs_thread}
        if kb:
            send_kwargs["reply_markup"] = kb
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
        log_msg_id = log_msg.message_id
    except Exception as exc:
        log.error("Ban log send failed: %s", exc)

    if log_msg_id:
        await db.bans_db.set_log_message_id(ban_id, log_msg_id)

    ## Enforce across all affiliated groups
    groups = await db.groups_db.active_groups()
    failed = 0
    for grp in groups:
        try:
            await bot.ban_chat_member(grp["chat_id"], target_id)
        except Exception:
            failed += 1

    ## Edit the original prompt to a summary
    summary = (
        f"{mention(target_id, target_fname)} (<code>{target_id}</code>) has been banned.\n"
        f"Reason: {reason}\n"
        f"Applied to {len(groups) - failed}/{len(groups)} groups."
    )
    if prompt_msg_id and prompt_chat_id:
        try:
            await bot.edit_message_text(
                summary, chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

    ## Cache target in member_cache
    await db.users_db.upsert_user(target_id, None, target_fname)


## ---------------------------------------------------------------------------
## Timeout fallback
## ---------------------------------------------------------------------------

async def on_ban_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text("Proof submission timed out.")
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Handler factory
## ---------------------------------------------------------------------------

def build_handler() -> ConversationHandler:
    entry = (
        build_prefixed_filters("tcban")
        | build_prefixed_filters("fban")
        | build_prefixed_filters("ban")
        | build_prefixed_filters("tcfban")
    )
    return ConversationHandler(
        entry_points=[MessageHandler(entry, cmd_ban_start)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(on_cancel_proof, pattern=r"^cancel_proof$"),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
            ],
        },
        fallbacks=[MessageHandler(filters.COMMAND, on_ban_timeout)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
