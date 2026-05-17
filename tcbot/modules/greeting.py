# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from tcbot import database as db
from tcbot import cfg
from tcbot.modules.helper.formatter import mention

log = logging.getLogger(__name__)


async def on_new_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    chat = update.effective_chat

    ## Only fire in MAIN_GROUP and EXEC_GROUP
    if chat.id not in (cfg.main_group, cfg.exec_group):
        return

    for member in msg.new_chat_members:
        if member.is_bot:
            continue

        ## Cache member and check for active ban in parallel
        _, ban = await asyncio.gather(
            db.users_db.upsert_user(
                member.id, member.username, member.first_name, member.last_name,
            ),
            db.bans_db.get_active_ban(member.id),
        )

        if ban:
            try:
                ## ban and reply in parallel
                await asyncio.gather(
                    ctx.bot.ban_chat_member(chat.id, member.id),
                    msg.reply_text(
                        f"{mention(member.id, member.first_name)} is federation-banned and was removed.",
                        parse_mode="HTML",
                    ),
                )
            except Exception as exc:
                log.error("Auto-ban on join failed: %s", exc)
            continue

        await msg.reply_text(
            f"Welcome, {mention(member.id, member.first_name)}! 👋 "
            f"This is an official {cfg.community_name} group. "
            "Please go through the group rules before participating.",
            parse_mode="HTML",
        )


async def on_left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    chat = update.effective_chat

    if chat.id not in (cfg.main_group, cfg.exec_group):
        return

    member = msg.left_chat_member
    if member and not member.is_bot:
        await msg.reply_text(
            f"{mention(member.id, member.first_name)} has left.",
            parse_mode="HTML",
        )


__handlers__ = [
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member),
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member),
]
