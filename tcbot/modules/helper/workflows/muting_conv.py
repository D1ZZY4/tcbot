# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""
Mute conversation workflow - reason + optional proof

Flow
────
1. /tcmute <target> [duration] [reason]
    → target   : reply / user-id / @username
    → duration : optional token matching  3s 5m 2h 7d 1w 3mo 2ye
    → reason   : everything else in the message

2. If reason was NOT given inline → WAITING_REASON
    • user sends plain text  → stored as reason, continue
    • Skip button pressed    → reason = "No reason provided", continue

3. WAITING_PROOF (always reached)
    • user sends photo/video → proof note stored, execute mute
    • Skip button pressed    → execute mute without proof
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot.database.roles_db import get_effective_role, role_rank, ROLE_LABEL
from tcbot.modules.helper import extraction, keyboards
from tcbot.modules.helper.formatter import code, mention
from tcbot.modules.helper.workflows.muting_flow import (
    _DURATION_RE,
    _execute_mute,
    fmt_duration,
    parse_duration,
)
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

WAITING_REASON = 0
WAITING_PROOF  = 1


async def _end_conversation(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Mute operation cancelled.")
    return ConversationHandler.END


## ── Entry point ────────────────────────────────────────────────────────────

async def cmd_mute_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg   = update.effective_message
    admin = update.effective_user

    raw_args = parse_cmd_args(msg.text)
    has_explicit_target = bool(raw_args) and (
        raw_args[0].lstrip("-").isdigit() or raw_args[0].startswith("@")
    )
    ## Role check and target resolution run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        get_effective_role(admin.id),
        extraction.extract_target(update, raw_args, ctx.bot),
    )
    if role_rank(executor_role) < role_rank("tester"):
        await msg.reply_text("You need at least a Tester role to mute - not your call. 🚫")
        return ConversationHandler.END
    remaining_args = list(raw_args[1:] if has_explicit_target else raw_args)

    if not target_id:
        await msg.reply_text("Cannot resolve target. Reply to a message or provide a user ID.")
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text(
            "Muting me won't do much - I don't send messages on my own anyway. 😄"
        )
        return ConversationHandler.END

    if target_id == admin.id:
        await msg.reply_text("Can't mute yourself - that's not how this works. 🙃")
        return ConversationHandler.END

    target_role = await get_effective_role(target_id)
    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            if target_role == "founder":
                await msg.reply_text(
                    f"That's {mention(target_id, target_fname or 'the Founder')}, our Founder - "
                    "muting them is not happening. 👑",
                    parse_mode="HTML",
                )
            else:
                label = ROLE_LABEL.get(target_role, target_role.capitalize())
                await msg.reply_text(
                    f"That's a {cfg.community_name} {label} - they outrank you here, can't mute them."
                )
            return ConversationHandler.END

    duration = None
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


## ── WAITING_REASON handlers ────────────────────────────────────────────────

async def on_reason_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["mute_reason"] = update.effective_message.text.strip()
    target_id    = ctx.user_data["mute_target_id"]
    target_fname = ctx.user_data["mute_target_fname"]
    duration     = ctx.user_data["mute_duration"]
    prompt_chat  = ctx.user_data["mute_prompt_chat"]
    prompt_id    = ctx.user_data.get("mute_prompt_id")
    dur_str      = fmt_duration(duration)
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
    except Exception as exc:
        log.error("Mute prompt edit failed (reason step): %s", exc)
    return WAITING_PROOF


async def on_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    ctx.user_data["mute_reason"] = "No reason provided"
    target_id    = ctx.user_data["mute_target_id"]
    target_fname = ctx.user_data["mute_target_fname"]
    duration     = ctx.user_data["mute_duration"]
    dur_str      = fmt_duration(duration)
    try:
        await asyncio.gather(
            q.answer(),
            q.edit_message_text(
                f"Muting {mention(target_id, target_fname)} {code(str(target_id))} {dur_str}.\n\n"
                f"Send proof (photo / video) or press <b>Skip</b>.",
                parse_mode="HTML",
                reply_markup=keyboards.mute_proof_kb(),
            ),
        )
    except Exception as exc:
        log.error("Mute prompt edit failed (skip-reason step): %s", exc)
    return WAITING_PROOF


## ── WAITING_PROOF handlers ─────────────────────────────────────────────────

async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg.photo:
        ctx.user_data["mute_proof_desc"] = f"Photo (msg {msg.message_id})"
    elif msg.video:
        ctx.user_data["mute_proof_desc"] = f"Video (msg {msg.message_id})"
    await _execute_mute(ctx.bot, update, ctx.user_data)
    return ConversationHandler.END


async def on_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        _execute_mute(ctx.bot, update, ctx.user_data),
    )
    return ConversationHandler.END


## ── Cancel ─────────────────────────────────────────────────────────────────

async def on_mute_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Got it, mute cancelled. No action was taken."),
    )
    return ConversationHandler.END


## ── ConversationHandler factory ────────────────────────────────────────────

## Unmute commands must NOT be caught by the fallback - if they are, the
## ConversationHandler consumes the update and cmd_unmute never runs.
## Excluding them here lets PTB fall through to the MessageHandler below.
_UNMUTE_ESCAPE = (
    build_prefixed_filters("tcunmute")
    | build_prefixed_filters("tcunm")
)


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
                MessageHandler(filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, on_reason_text),
            ],
            WAITING_PROOF: [
                CallbackQueryHandler(on_skip_proof,  pattern=r"^mute_skip_proof$"),
                CallbackQueryHandler(on_mute_cancel, pattern=r"^mute_cancel$"),
                MessageHandler(filters.PHOTO | filters.VIDEO, on_proof_received),
            ],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER & ~_UNMUTE_ESCAPE, _end_conversation)],
        conversation_timeout=cfg.proof_timeout,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
