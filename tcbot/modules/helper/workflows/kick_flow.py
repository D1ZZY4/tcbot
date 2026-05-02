# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Kick flow helpers – group-level user removal."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper.formatter import code, mention

log = logging.getLogger(__name__)


async def execute_kick(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason: str,
    proof_desc: str | None = None,
) -> None:
    """Kick (ban then immediately unban) a user from the current group."""
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id

    try:
        await ctx.bot.ban_chat_member(chat_id, target_id)
        await ctx.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        await db.kicks_db.log_kick(target_id, chat_id, reason, admin_id)
        proof_line = f"\nProof: {proof_desc}" if proof_desc else ""
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has been kicked.\n"
            f"Reason: {reason}{proof_line}",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Kick failed for %s in %s: %s", target_id, chat_id, exc)
        await msg.reply_text(
            f"Failed to kick {mention(target_id, target_name)}: {exc}",
            parse_mode="HTML",
        )
