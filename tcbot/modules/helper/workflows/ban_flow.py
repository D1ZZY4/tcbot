# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Ban conversation workflow – no confirm step, proof only, immediate execution
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
from tcbot import cfg
from tcbot.database.roles_db import get_effective_role, role_rank
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import appeal_deep_link, message_link
from tcbot.utils.dispatch import fan_out
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters
from tcbot.utils.timedate_format import utc_now

log = logging.getLogger(__name__)

WAITING_PROOF = 0

## Module-level album accumulators
_albums: dict[str, list[Message]] = {}
_album_meta: dict[str, dict[str, Any]] = {}


## ── Proof received ─────────────────────────────────────────────────────────

async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    uid = update.effective_user.id

    if role_rank(await get_effective_role(uid)) < role_rank("developer"):
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


## ── Cancel callback ────────────────────────────────────────────────────────

async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Cancelled. No ban was issued.")
    return ConversationHandler.END


## ── Core ban execution ─────────────────────────────────────────────────────

async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict) -> None:
    target_id: int    = meta.get("ban_target_id")
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    reason: str       = meta.get("ban_reason", "No reason provided")
    admin_id: int     = meta.get("ban_admin_id")
    admin_fname: str  = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int  = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)

    now = utc_now()
    proof_chat, proof_thread = cfg.proofs

    ## Determine new vs update
    existing  = await db.bans_db.get_active_ban(target_id)
    is_update = existing is not None

    ## Build proof caption
    if is_update:
        prev_proof_msg_id = existing.get("proof_message_id")
        prev_proof_link   = (
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

    logs_chat, logs_thread = cfg.logs

    if is_update:
        ban_id        = existing["ban_id"]
        old_admin_id  = existing.get("admin_user_id", admin_id)

        ## old admin name fetched while bot.username is a free property access
        bot_username    = bot.username
        old_admin_fname = await db.users_db.get_first_name(old_admin_id, "Admin")

        log_text = parse_logmsg.ban_update_log(
            target_id, target_fname,
            admin_id, admin_fname,
            old_admin_id, old_admin_fname,
            reason, ban_id,
            existing.get("timestamp", now),
            proof_link, prev_proof_link,
        )
        _appeal_url = appeal_deep_link(bot_username, ban_id)
        kb = keyboards.ban_log_update(
            target_id, proof_link, prev_proof_link, _appeal_url,
        ) if proof_link and prev_proof_link else (
            keyboards.ban_log_new(target_id, proof_link, _appeal_url)
            if proof_link else None
        )

        ## Update DB record and send log in parallel
        send_kwargs: dict = {"parse_mode": "HTML", "message_thread_id": logs_thread}
        if kb:
            send_kwargs["reply_markup"] = kb
        _, log_result = await asyncio.gather(
            db.bans_db.update_ban(
                ban_id, reason, admin_id,
                proof_msg_id or 0, 0,
                existing.get("proof_message_id", 0),
                existing.get("log_message_id", 0),
            ),
            bot.send_message(logs_chat, log_text, **send_kwargs),
            return_exceptions=True,
        )
    else:
        ## Pre-generate ban_id so we can use it in the log keyboard
        ban_id = db.bans_db.make_ban_id()

        bot_username = bot.username or "TCFBot"

        log_text = parse_logmsg.ban_log(
            target_id, target_fname, admin_id, admin_fname,
            reason, ban_id, proof_link, now,
        )
        kb = keyboards.ban_log_new(
            target_id, proof_link, appeal_deep_link(bot_username, ban_id),
        ) if proof_link else None

        ## Create DB record and send log in parallel
        send_kwargs = {"parse_mode": "HTML", "message_thread_id": logs_thread}
        if kb:
            send_kwargs["reply_markup"] = kb
        _, log_result = await asyncio.gather(
            db.bans_db.create_ban(target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id),
            bot.send_message(logs_chat, log_text, **send_kwargs),
            return_exceptions=True,
        )

    ## Extract log_msg_id from parallel result
    log_msg_id: int = 0
    if not isinstance(log_result, BaseException):
        log_msg_id = log_result.message_id
    else:
        log.error("Ban log send failed: %s", log_result)

    ## set_log_message_id and active_groups fetched in parallel
    if log_msg_id:
        _, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            db.groups_db.active_groups(),
        )
    else:
        groups = await db.groups_db.active_groups()

    ## Enforce across all connected groups — semaphore-bounded for rate safety
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    failed = sum(1 for r in results if isinstance(r, BaseException))

    ## Edit the original prompt to a summary + cache user in parallel
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


## ── Timeout fallback ───────────────────────────────────────────────────────

async def on_ban_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Timed out waiting for proof. No ban was issued."
        )
    return ConversationHandler.END


## ── Handler factory ────────────────────────────────────────────────────────

def build_handler(entry_fn) -> ConversationHandler:
    entry = (
        build_prefixed_filters("tcban")
        | build_prefixed_filters("tcb")
    )
    return ConversationHandler(
        entry_points=[MessageHandler(entry, entry_fn)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(on_cancel_proof, pattern=r"^cancel_proof$"),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
            ],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER, on_ban_timeout)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
