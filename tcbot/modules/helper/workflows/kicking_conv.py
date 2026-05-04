# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Kick conversation workflow — reason + optional proof.

Flow
────
1. /tckick <target> [reason]
   – target  : reply / user-id / @username
   – reason  : optional, everything else in the message

2. If reason was NOT given inline → WAITING_REASON
     • user sends plain text       → stored as reason, continue
     • Skip button pressed         → reason = "No reason provided", continue

3. WAITING_PROOF (always reached)
     • user sends photo/video      → proof description noted, execute kick
     • Skip button pressed         → execute kick without proof
     • Cancel button pressed       → cancel flow
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot.database.roles_db import get_effective_role, role_rank, ROLE_LABEL
from tcbot.modules.helper import extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.role_guard import auto_demote
from tcbot.modules.helper.workflows.kicking_flow import execute_kick
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

WAITING_REASON = 0
WAITING_PROOF  = 1

_KB_REASON = InlineKeyboardMarkup([[
    InlineKeyboardButton("Skip",   callback_data="kick_skip_reason"),
    InlineKeyboardButton("Cancel", callback_data="kick_cancel"),
]])

_KB_PROOF = InlineKeyboardMarkup([[
    InlineKeyboardButton("Skip",   callback_data="kick_skip_proof"),
    InlineKeyboardButton("Cancel", callback_data="kick_cancel"),
]])


## ---------------------------------------------------------------------------
## Helpers
## ---------------------------------------------------------------------------

def _clear(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("kick_target_id", "kick_target_name", "kick_reason", "kick_proof_desc"):
        ctx.user_data.pop(k, None)


async def _do_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    target_id   = ctx.user_data["kick_target_id"]
    target_name = ctx.user_data["kick_target_name"]
    reason      = ctx.user_data.get("kick_reason", "No reason provided")
    proof_desc  = ctx.user_data.get("kick_proof_desc")
    _clear(ctx)
    await execute_kick(update, ctx, target_id, target_name, reason, proof_desc=proof_desc)
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Entry point
## ---------------------------------------------------------------------------

async def cmd_kick_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg   = update.effective_message
    admin = update.effective_user

    executor_role = await get_effective_role(admin.id)
    if role_rank(executor_role) < role_rank("tester"):
        await msg.reply_text("You need at least a Tester role to kick — not your call. 🚫")
        return ConversationHandler.END

    args = parse_cmd_args(msg.text)

    if msg.reply_to_message:
        target_id, target_name = await extraction.extract_target(update, [], ctx.bot)
        inline_reason = " ".join(args).strip()
    else:
        target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
        inline_reason = " ".join(args[1:]).strip()

    if not target_id:
        await msg.reply_text(
            "Can't find that user — reply to their message or send me a user ID."
        )
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text("Kick me? 😂 I run this place. Not happening.")
        return ConversationHandler.END

    target_role = await get_effective_role(target_id)
    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            if target_role == "founder":
                await msg.reply_text(
                    f"That's {mention(target_id, target_name or 'the Founder')}, our Founder — "
                    "kicking the boss? Not happening. 👑",
                    parse_mode="HTML",
                )
            else:
                label = ROLE_LABEL.get(target_role, target_role.capitalize())
                await msg.reply_text(
                    f"That's a {cfg.community_name} {label} — they outrank you here, can't kick them."
                )
            return ConversationHandler.END
        await auto_demote(
            ctx.bot,
            target_id, target_name or str(target_id), target_role,
            admin.id, admin.first_name, "kick",
        )

    ctx.user_data.update({
        "kick_target_id":   target_id,
        "kick_target_name": target_name or str(target_id),
        "kick_proof_desc":  None,
    })

    target_mention = mention(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["kick_reason"] = inline_reason
        await msg.reply_text(
            f"Kicking {target_mention}.\n"
            f"Reason: <b>{inline_reason}</b>\n\n"
            "Got any proof? Send a photo or video, or tap <b>Skip</b> to proceed.",
            parse_mode="HTML",
            reply_markup=_KB_PROOF,
        )
        return WAITING_PROOF

    await msg.reply_text(
        f"About to kick {target_mention}.\n"
        "What's the reason? Type it below, or tap <b>Skip</b>.",
        parse_mode="HTML",
        reply_markup=_KB_REASON,
    )
    return WAITING_REASON


## ---------------------------------------------------------------------------
## WAITING_REASON handlers
## ---------------------------------------------------------------------------

async def on_kick_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["kick_reason"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        "Reason noted. Send proof (photo or video) if you have any, "
        "or tap <b>Skip</b> to proceed.",
        parse_mode="HTML",
        reply_markup=_KB_PROOF,
    )
    return WAITING_PROOF


async def on_kick_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    ctx.user_data["kick_reason"] = "No reason provided"
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            "No reason — send proof (photo or video) if any, "
            "or tap <b>Skip</b> to proceed.",
            parse_mode="HTML",
            reply_markup=_KB_PROOF,
        ),
    )
    return WAITING_PROOF


## ---------------------------------------------------------------------------
## WAITING_PROOF handlers
## ---------------------------------------------------------------------------

async def on_kick_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg.photo:
        ctx.user_data["kick_proof_desc"] = f"Photo (msg {msg.message_id})"
    elif msg.video:
        ctx.user_data["kick_proof_desc"] = f"Video (msg {msg.message_id})"
    return await _do_kick(update, ctx)


async def on_kick_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _do_kick(update, ctx)


async def on_kick_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    _clear(ctx)
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Got it, kick cancelled. No action was taken."),
    )
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## ConversationHandler factory
## ---------------------------------------------------------------------------

_KICK_FILTER = build_prefixed_filters("tckick") | build_prefixed_filters("tck")


def kick_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(_KICK_FILTER, cmd_kick_entry)],
        states={
            WAITING_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_kick_reason),
                CallbackQueryHandler(on_kick_skip_reason, pattern=r"^kick_skip_reason$"),
                CallbackQueryHandler(on_kick_cancel,      pattern=r"^kick_cancel$"),
            ],
            WAITING_PROOF: [
                MessageHandler(filters.PHOTO | filters.VIDEO, on_kick_proof),
                CallbackQueryHandler(on_kick_skip_proof, pattern=r"^kick_skip_proof$"),
                CallbackQueryHandler(on_kick_cancel,     pattern=r"^kick_cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(on_kick_cancel, pattern=r"^kick_cancel$")],
        per_user=True,
        per_chat=True,
        conversation_timeout=cfg.proof_timeout,
    )
