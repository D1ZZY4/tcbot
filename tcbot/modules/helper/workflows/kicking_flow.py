# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""
Kick executor — group-level user removal (ban + immediate unban)
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import cfg, database as db
from tcbot.modules.helper import parse_logmsg
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
    msg      = update.effective_message
    chat_id  = update.effective_chat.id
    admin_id = update.effective_user.id

    try:
        await ctx.bot.ban_chat_member(chat_id, target_id)
        proof_line  = f"\nProof: {proof_desc}" if proof_desc else ""
        chat_title  = update.effective_chat.title or str(chat_id)
        admin_fname = update.effective_user.first_name
        lc, lt      = cfg.logs
        log_text    = parse_logmsg.kick_log(
            target_id, target_name, admin_id, admin_fname, reason, chat_id, chat_title,
        )
        ## unban + log_kick + federation log + reply all run in parallel
        results = await asyncio.gather(
            ctx.bot.unban_chat_member(chat_id, target_id, only_if_banned=True),
            db.kicks_db.log_kick(target_id, chat_id, reason, admin_id),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            msg.reply_text(
                f"{mention(target_id, target_name)} {code(str(target_id))} has been kicked.\n"
                f"Reason: {reason}{proof_line}\n"
                "They can rejoin via invite link.",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
        if isinstance(results[2], BaseException):
            log.error("Kick log send failed: %s", results[2])
    except Exception as exc:
        log.error("Kick failed for %s in %s: %s", target_id, chat_id, exc)
        await msg.reply_text(
            f"Couldn't kick {mention(target_id, target_name)}: {exc}",
            parse_mode="HTML",
        )
