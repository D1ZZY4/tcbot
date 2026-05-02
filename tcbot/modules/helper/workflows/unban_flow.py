# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Unban flow – invoked directly by the unban command."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import code, mention

log = logging.getLogger(__name__)


async def execute_unban(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_fname: str,
) -> None:
    msg = update.effective_message
    admin = update.effective_user

    ban = await db.bans_db.get_active_ban(target_id)
    if not ban:
        await msg.reply_text(
            f"{mention(target_id, target_fname)} {code(str(target_id))} has no active federation ban.",
            parse_mode="HTML",
        )
        return

    ban_id = ban["ban_id"]
    await db.bans_db.deactivate_ban(ban_id)

    groups = await db.groups_db.active_groups()
    failed = 0
    for grp in groups:
        try:
            await ctx.bot.unban_chat_member(grp["chat_id"], target_id, only_if_banned=True)
        except Exception:
            failed += 1

    lc, lt = cfg.logs
    log_text = parse_logmsg.unban_log(
        target_id, target_fname, admin.id, admin.first_name, ban_id,
    )
    try:
        await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Unban log failed: %s", exc)

    await msg.reply_text(
        f"{mention(target_id, target_fname)} {code(str(target_id))} has been unbanned.\n"
        f"Removed from {len(groups) - failed}/{len(groups)} groups.",
        parse_mode="HTML",
    )
