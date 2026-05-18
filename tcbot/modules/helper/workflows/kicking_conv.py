# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Kick conversation workflow - reason + optional proof

Flow
────
1. /tckick <target> [reason]
    → target  : reply / user-id / @username
    → reason  : optional inline

2. If reason was NOT given inline → WAITING_REASON
    • user sends plain text       → stored as reason, continue
    • Skip button pressed         → default reason used, continue
    • Cancel button pressed       → conversation ends, no action

3. WAITING_PROOF (always reached)
    • user sends photo/video      → proof desc noted, execute kick
    • Skip button pressed         → execute kick without proof
    • Cancel button pressed       → conversation ends, no action
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
from tcbot.modules.helper.workflows.kicking_flow import execute_kick
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

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


## ── Helpers ────────────────────────────────────────────────────────────────

def _clear(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("kick_target_id", "kick_target_name", "kick_reason", "kick_proof_desc"):
        ctx.user_data.pop(k, None)


async def _end_conversation(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(ctx)
    await update.effective_message.reply_text("Kick operation cancelled.")
    return ConversationHandler.END


async def _do_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    target_id   = ctx.user_data["kick_target_id"]
    target_name = ctx.user_data["kick_target_name"]
    reason      = ctx.user_data.get("kick_reason", "No reason provided")
    proof_desc  = ctx.user_data.get("kick_proof_desc")
    _clear(ctx)
    await execute_kick(update, ctx, target_id, target_name, reason, proof_desc=proof_desc)
    return ConversationHandler.END


## ── WAITING_REASON handlers ────────────────────────────────────────────────

async def on_kick_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the reason - store it and ask for proof."""
    ctx.user_data["kick_reason"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        "Reason noted. Send proof (photo or video) if you have any, "
        "or tap <b>Skip</b> to proceed.",
        parse_mode="HTML",
        reply_markup=_KB_PROOF,
    )
    return WAITING_PROOF


async def on_kick_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip button in reason state - use default reason and ask for proof."""
    q = update.callback_query
    ctx.user_data["kick_reason"] = "No reason provided"
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            "No reason - send proof (photo or video) if any, "
            "or tap <b>Skip</b> to proceed.",
            parse_mode="HTML",
            reply_markup=_KB_PROOF,
        ),
    )
    return WAITING_PROOF


## ── WAITING_PROOF handlers ─────────────────────────────────────────────────

async def on_kick_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """User sent a photo or video as proof - record it and execute kick."""
    msg = update.effective_message
    if msg.photo:
        ctx.user_data["kick_proof_desc"] = f"Photo (msg {msg.message_id})"
    elif msg.video:
        ctx.user_data["kick_proof_desc"] = f"Video (msg {msg.message_id})"
    return await _do_kick(update, ctx)


async def on_kick_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip button in proof state - execute kick without proof."""
    await update.callback_query.answer()
    return await _do_kick(update, ctx)


async def on_kick_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel button in any state - discard all pending kick data."""
    q = update.callback_query
    _clear(ctx)
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Got it, kick cancelled. No action was taken."),
    )
    return ConversationHandler.END


## ── ConversationHandler factory ────────────────────────────────────────────

_KICK_FILTER = build_prefixed_filters("tckick") | build_prefixed_filters("tck")


def build_handler(entry_point) -> ConversationHandler:
    """Return a ConversationHandler for the kick flow.

    Args:
        entry_point: The entry MessageHandler callback (``cmd_kick_entry`` from
            ``kicking.py``), passed in to avoid circular imports.
    """
    return ConversationHandler(
        entry_points=[MessageHandler(_KICK_FILTER, entry_point)],
        states={
            WAITING_REASON: [
                MessageHandler(filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, on_kick_reason),
                CallbackQueryHandler(on_kick_skip_reason, pattern=r"^kick_skip_reason$"),
                CallbackQueryHandler(on_kick_cancel,      pattern=r"^kick_cancel$"),
            ],
            WAITING_PROOF: [
                MessageHandler(filters.PHOTO | filters.VIDEO, on_kick_proof),
                CallbackQueryHandler(on_kick_skip_proof, pattern=r"^kick_skip_proof$"),
                CallbackQueryHandler(on_kick_cancel,     pattern=r"^kick_cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(on_kick_cancel, pattern=r"^kick_cancel$"),
            MessageHandler(ALL_PREFIXES_CMD_FILTER, _end_conversation),
        ],
        per_user=True,
        per_chat=True,
        conversation_timeout=cfg.proof_timeout,
    )
