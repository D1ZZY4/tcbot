# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Unban flow - invoked directly by the unban command."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.utils.dispatch import fan_out

log = logging.getLogger(__name__)


# ───────────────────────── Unban executor ───────────────────────── #


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
            f"{mention(target_id, target_fname)} has no active federation ban.",
            parse_mode="HTML",
        )
        return

    ban_id = ban["ban_id"]

    # * deactivate ban and fetch active groups in parallel
    _, groups = await asyncio.gather(
        db.bans_db.deactivate_ban(ban_id),
        db.groups_db.active_groups(),
    )

    # * unban from all groups - semaphore-bounded for rate safety
    results = await fan_out(
        [
            ctx.bot.unban_chat_member(grp["chat_id"], target_id, only_if_banned=True)
            for grp in groups
        ]
    )
    failed = sum(1 for r in results if isinstance(r, BaseException))

    lc, lt = cfg.logs
    log_text = parse_logmsg.unban_log(
        target_id,
        target_fname,
        admin.id,
        admin.first_name,
        ban_id,
    )

    # * send log and reply in parallel
    await asyncio.gather(
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"{mention(target_id, target_fname)} has been unbanned - "
            f"removed from {len(groups) - failed}/{len(groups)} groups.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
