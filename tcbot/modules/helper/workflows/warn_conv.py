# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Warn conversation workflow — reason + optional proof.

Flow
────
1. /tcwarn <target> [reason]
   – target  : reply / user-id / @username
   – reason  : optional inline, but required to proceed

2. If reason was NOT given inline → WAITING_REASON
     • user sends plain text       → stored as reason, continue
     • (no skip — a reason is required for a warning)

3. WAITING_PROOF (always reached)
     • user sends photo/video      → proof description noted, execute warn
     • Skip button pressed         → execute warn without proof
     • Cancel button pressed       → cancel flow
"""
from __future__ import annotations

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
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.warning_flow import execute_warn
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

WAITING_REASON = 0
WAITING_PROOF  = 1

_KB_REASON = InlineKeyboardMarkup([[
    InlineKeyboardButton("Cancel", callback_data="warn_cancel"),
]])

_KB_PROOF = InlineKeyboardMarkup([[
    InlineKeyboardButton("Skip", callback_data="warn_skip_proof"),
    InlineKeyboardButton("Cancel", callback_data="warn_cancel"),
]])


## ---------------------------------------------------------------------------
## Helpers
## ---------------------------------------------------------------------------

def _clear(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("warn_target_id", "warn_target_name", "warn_reason", "warn_proof_desc"):
        ctx.user_data.pop(k, None)


async def _do_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    target_id   = ctx.user_data["warn_target_id"]
    target_name = ctx.user_data["warn_target_name"]
    reason      = ctx.user_data["warn_reason"]
    proof_desc  = ctx.user_data.get("warn_proof_desc")
    _clear(ctx)
    await execute_warn(update, ctx, target_id, target_name, reason, proof_desc=proof_desc)
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Entry point
## ---------------------------------------------------------------------------

@decorators.staff_only
async def cmd_warn_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg  = update.effective_message
    args = parse_cmd_args(msg.text)

    if msg.reply_to_message:
        target_id, target_name = await extraction.extract_target(update, [], ctx.bot)
        inline_reason = " ".join(args).strip()
    else:
        target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
        inline_reason = " ".join(args[1:]).strip()

    if not target_id:
        await msg.reply_text(
            "Can't find that user — reply to their message or give me an ID."
        )
        return ConversationHandler.END

    ctx.user_data.update({
        "warn_target_id":   target_id,
        "warn_target_name": target_name or str(target_id),
        "warn_proof_desc":  None,
    })

    target_mention = mention(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["warn_reason"] = inline_reason
        await msg.reply_text(
            f"Warning {target_mention}.\n"
            f"Reason: <b>{inline_reason}</b>\n\n"
            "Got any proof? Send a photo or video, or tap <b>Skip</b>.",
            parse_mode="HTML",
            reply_markup=_KB_PROOF,
        )
        return WAITING_PROOF

    await msg.reply_text(
        f"About to warn {target_mention}.\n"
        "A reason is required — type it below. Or tap <b>Cancel</b> to abort.",
        parse_mode="HTML",
        reply_markup=_KB_REASON,
    )
    return WAITING_REASON


## ---------------------------------------------------------------------------
## WAITING_REASON handlers
## ---------------------------------------------------------------------------

async def on_warn_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["warn_reason"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        "Reason noted! Send proof (photo or video) if you have any, "
        "or tap <b>Skip</b> to issue the warning now.",
        parse_mode="HTML",
        reply_markup=_KB_PROOF,
    )
    return WAITING_PROOF


## ---------------------------------------------------------------------------
## WAITING_PROOF handlers
## ---------------------------------------------------------------------------

async def on_warn_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg.photo:
        ctx.user_data["warn_proof_desc"] = f"Photo (msg {msg.message_id})"
    elif msg.video:
        ctx.user_data["warn_proof_desc"] = f"Video (msg {msg.message_id})"
    return await _do_warn(update, ctx)


async def on_warn_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _do_warn(update, ctx)


async def on_warn_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _clear(ctx)
    await q.edit_message_text("Warning cancelled. No action taken.")
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## ConversationHandler factory
## ---------------------------------------------------------------------------

_WARN_FILTER = build_prefixed_filters("tcwarn") | build_prefixed_filters("tcw")


def warn_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(_WARN_FILTER, cmd_warn_entry)],
        states={
            WAITING_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_warn_reason),
                CallbackQueryHandler(on_warn_cancel, pattern=r"^warn_cancel$"),
            ],
            WAITING_PROOF: [
                MessageHandler(filters.PHOTO | filters.VIDEO, on_warn_proof),
                CallbackQueryHandler(on_warn_skip_proof, pattern=r"^warn_skip_proof$"),
                CallbackQueryHandler(on_warn_cancel,     pattern=r"^warn_cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(on_warn_cancel, pattern=r"^warn_cancel$")],
        per_user=True,
        per_chat=True,
        conversation_timeout=cfg.proof_timeout,
    )
