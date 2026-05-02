# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Mute/unmute conversation workflow.

Flow
────
1. /tcmute <target> [duration] [reason]
   – target   : reply / user-id / @username
   – duration : optional token matching  3s 5m 2h 7d 1w 3mo 2ye
   – reason   : everything else in the message

2. If reason was NOT given inline → WAITING_REASON
     • user sends plain text  → stored as reason, continue
     • Skip button pressed    → reason = "No reason provided", continue

3. WAITING_PROOF (always reached)
     • user sends photo/video → proof note stored, execute mute
     • Skip button pressed    → execute mute without proof

Duration units
──────────────
s  = seconds   m  = minutes   h  = hours
d  = days      w  = weeks     mo = months (30 d)   ye = years (365 d)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, InputMediaPhoto, InputMediaVideo, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg, database as db
from tcbot.modules.helper import keyboards
from tcbot.modules.helper.formatter import code, mention
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

WAITING_REASON = 0
WAITING_PROOF  = 1

_DURATION_RE = re.compile(r"^(\d+)(ye|mo|[smhdw])$", re.IGNORECASE)


## ---------------------------------------------------------------------------
## Duration helpers
## ---------------------------------------------------------------------------

def parse_duration(raw: str) -> timedelta | None:
    """Parse a single duration token like '3d', '1mo', '2ye'. Returns None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    value = int(m.group(1))
    unit  = m.group(2).lower()
    mapping = {
        "s":  timedelta(seconds=value),
        "m":  timedelta(minutes=value),
        "h":  timedelta(hours=value),
        "d":  timedelta(days=value),
        "w":  timedelta(weeks=value),
        "mo": timedelta(days=value * 30),
        "ye": timedelta(days=value * 365),
    }
    return mapping.get(unit)


def fmt_duration(td: timedelta | None) -> str:
    """Human-readable duration string for use in replies."""
    if td is None:
        return "permanently"
    total = int(td.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    days = total // 86400
    if days < 7:
        return f"{days}d"
    if days < 30:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}ye"


## ---------------------------------------------------------------------------
## Entry point
## ---------------------------------------------------------------------------

async def cmd_mute_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg   = update.effective_message
    admin = update.effective_user

    if not await db.admins_db.is_staff(admin.id):
        await msg.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    raw_args = parse_cmd_args(msg.text)

    if msg.reply_to_message:
        from tcbot.modules.helper import extraction
        target_id, target_fname = await extraction.extract_target(update, [], ctx.bot)
        remaining_args = list(raw_args)
    else:
        from tcbot.modules.helper import extraction
        target_id, target_fname = await extraction.extract_target(update, raw_args, ctx.bot)
        remaining_args = list(raw_args[1:]) if raw_args else []

    if not target_id:
        await msg.reply_text("Cannot resolve target. Reply to a message or provide a user ID.")
        return ConversationHandler.END

    if target_id == admin.id:
        await msg.reply_text("You cannot mute yourself.")
        return ConversationHandler.END

    if await db.admins_db.is_owner(target_id):
        await msg.reply_text("The owner cannot be muted.")
        return ConversationHandler.END

    duration: timedelta | None = None
    if remaining_args and _DURATION_RE.match(remaining_args[0]):
        duration = parse_duration(remaining_args.pop(0))

    inline_reason = " ".join(remaining_args).strip()

    ctx.user_data.update({
        "mute_target_id":    target_id,
        "mute_target_fname": target_fname or str(target_id),
        "mute_duration":     duration,
        "mute_admin_id":     admin.id,
        "mute_admin_fname":  admin.first_name,
        "mute_prompt_chat":  msg.chat.id,
        "mute_reason":       "",
        "mute_proof_desc":   None,
    })

    if inline_reason:
        ctx.user_data["mute_reason"] = inline_reason
        dur_str = fmt_duration(duration)
        prompt = await msg.reply_text(
            f"Muting {mention(target_id, target_fname or str(target_id))} "
            f"{code(str(target_id))} {dur_str}.\n"
            f"Reason: <i>{inline_reason}</i>\n\n"
            f"Send proof (photo / video) or press <b>Skip</b>.",
            parse_mode="HTML",
            reply_markup=keyboards.mute_proof_kb(),
        )
        ctx.user_data["mute_prompt_id"] = prompt.message_id
        return WAITING_PROOF

    dur_str = fmt_duration(duration)
    prompt = await msg.reply_text(
        f"Muting {mention(target_id, target_fname or str(target_id))} "
        f"{code(str(target_id))} {dur_str}.\n\n"
        f"Send a <b>reason</b> or press <b>Skip</b>.",
        parse_mode="HTML",
        reply_markup=keyboards.mute_reason_kb(),
    )
    ctx.user_data["mute_prompt_id"] = prompt.message_id
    return WAITING_REASON


## ---------------------------------------------------------------------------
## WAITING_REASON handlers
## ---------------------------------------------------------------------------

async def on_reason_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["mute_reason"] = update.effective_message.text.strip()
    target_id    = ctx.user_data["mute_target_id"]
    target_fname = ctx.user_data["mute_target_fname"]
    duration     = ctx.user_data["mute_duration"]
    prompt_chat  = ctx.user_data["mute_prompt_chat"]
    prompt_id    = ctx.user_data.get("mute_prompt_id")

    dur_str = fmt_duration(duration)
    try:
        await ctx.bot.edit_message_text(
            f"Muting {mention(target_id, target_fname)} {code(str(target_id))} {dur_str}.\n"
            f"Reason: <i>{ctx.user_data['mute_reason']}</i>\n\n"
            f"Send proof (photo / video) or press <b>Skip</b>.",
            chat_id=prompt_chat,
            message_id=prompt_id,
            parse_mode="HTML",
            reply_markup=keyboards.mute_proof_kb(),
        )
    except Exception:
        pass
    return WAITING_PROOF


async def on_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["mute_reason"] = "No reason provided"
    target_id    = ctx.user_data["mute_target_id"]
    target_fname = ctx.user_data["mute_target_fname"]
    duration     = ctx.user_data["mute_duration"]
    dur_str      = fmt_duration(duration)
    try:
        await q.edit_message_text(
            f"Muting {mention(target_id, target_fname)} {code(str(target_id))} {dur_str}.\n\n"
            f"Send proof (photo / video) or press <b>Skip</b>.",
            parse_mode="HTML",
            reply_markup=keyboards.mute_proof_kb(),
        )
    except Exception:
        pass
    return WAITING_PROOF


## ---------------------------------------------------------------------------
## WAITING_PROOF handlers
## ---------------------------------------------------------------------------

async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    uid = update.effective_user.id
    if not await db.admins_db.is_staff(uid):
        return WAITING_PROOF

    if msg.photo:
        ctx.user_data["mute_proof_desc"] = f"Photo (msg {msg.message_id})"
    elif msg.video:
        ctx.user_data["mute_proof_desc"] = f"Video (msg {msg.message_id})"

    await _execute_mute(ctx.bot, update, ctx.user_data)
    return ConversationHandler.END


async def on_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await _execute_mute(q._bot, update, ctx.user_data)
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Cancel
## ---------------------------------------------------------------------------

async def on_mute_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Mute cancelled.")
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Core execution
## ---------------------------------------------------------------------------

async def _execute_mute(bot, update: Update, meta: dict) -> None:
    target_id    = meta["mute_target_id"]
    target_fname = meta["mute_target_fname"]
    reason       = meta.get("mute_reason") or "No reason provided"
    admin_id     = meta["mute_admin_id"]
    admin_fname  = meta["mute_admin_fname"]
    duration     = meta.get("mute_duration")
    proof_desc   = meta.get("mute_proof_desc")
    prompt_chat  = meta.get("mute_prompt_chat")
    prompt_id    = meta.get("mute_prompt_id")
    dur_str      = fmt_duration(duration)

    chat_id = update.effective_chat.id
    until   = datetime.now(timezone.utc) + duration if duration else None

    try:
        await bot.restrict_chat_member(
            chat_id, target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await db.mutes_db.log_mute(target_id, chat_id, reason, admin_id)
    except Exception as exc:
        log.error("Mute failed for %s in %s: %s", target_id, chat_id, exc)
        try:
            await bot.edit_message_text(
                f"Failed to mute {mention(target_id, target_fname)}: {exc}",
                chat_id=prompt_chat, message_id=prompt_id, parse_mode="HTML",
            )
        except Exception:
            pass
        return

    proof_line = f"\nProof: {proof_desc}" if proof_desc else ""
    summary = (
        f"{mention(target_id, target_fname)} {code(str(target_id))} "
        f"has been muted <b>{dur_str}</b>.\n"
        f"Reason: {reason}"
        f"{proof_line}"
    )

    try:
        await bot.edit_message_text(
            summary,
            chat_id=prompt_chat, message_id=prompt_id,
            parse_mode="HTML", reply_markup=None,
        )
    except Exception:
        msg = update.effective_message
        if msg:
            await msg.reply_text(summary, parse_mode="HTML")


## ---------------------------------------------------------------------------
## Unmute execution
## ---------------------------------------------------------------------------

async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    msg     = update.effective_message
    chat_id = update.effective_chat.id
    try:
        await ctx.bot.restrict_chat_member(
            chat_id, target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            ),
        )
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has been unmuted.",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Unmute failed for %s in %s: %s", target_id, chat_id, exc)
        await msg.reply_text(
            f"Failed to unmute {mention(target_id, target_name)}: {exc}",
            parse_mode="HTML",
        )


## ---------------------------------------------------------------------------
## ConversationHandler factory
## ---------------------------------------------------------------------------

def build_handler() -> ConversationHandler:
    _entry = (
        build_prefixed_filters("tcmute")
        | build_prefixed_filters("tcm")
    )
    return ConversationHandler(
        entry_points=[MessageHandler(_entry, cmd_mute_start)],
        states={
            WAITING_REASON: [
                CallbackQueryHandler(on_skip_reason, pattern=r"^mute_skip_reason$"),
                CallbackQueryHandler(on_mute_cancel, pattern=r"^mute_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_reason_text),
            ],
            WAITING_PROOF: [
                CallbackQueryHandler(on_skip_proof,  pattern=r"^mute_skip_proof$"),
                CallbackQueryHandler(on_mute_cancel, pattern=r"^mute_cancel$"),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
            ],
        },
        fallbacks=[MessageHandler(filters.COMMAND, on_mute_cancel)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
