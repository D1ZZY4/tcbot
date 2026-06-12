# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, MessageHandler, filters

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.formatter import esc, mention

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, Update, User

log = logging.getLogger(__name__)


# ───────────────────────── Member Handlers ──────────────────────── #


async def _handle_member(member: User, msg: Message, chat: Chat, bot: Bot) -> None:
    """Process a single new member: cache, ban-check, then greet or remove."""
    if member.is_bot:
        return

    _, ban = await asyncio.gather(
        db.users_cache.upsert_user(
            member.id,
            member.username,
            member.first_name,
            member.last_name,
        ),
        db.bans_db.get_active_ban(member.id),
        return_exceptions=True,
    )
    if isinstance(ban, BaseException):
        log.error("get_active_ban failed on join for uid=%d: %s", member.id, ban)
        ban = None

    if ban:
        ban_exc, reply_exc = await asyncio.gather(
            bot.ban_chat_member(chat.id, member.id),
            msg.reply_text(
                f"{mention(member.id, member.first_name, member.username)} is federation-banned and was removed.",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
        if isinstance(ban_exc, BaseException):
            log.error("Auto-ban on join failed for uid=%d: %s", member.id, ban_exc)
        elif isinstance(reply_exc, BaseException):
            log.debug("Auto-ban reply failed for uid=%d: %s", member.id, reply_exc)
        return

    try:
        await msg.reply_text(
            f"Welcome, {mention(member.id, member.first_name, member.username)}. "
            f"This is an official {esc(cfg.community_name)} group. "
            "Please go through the group rules before participating.",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.debug("Welcome reply failed for uid=%d: %s", member.id, exc)


@decorators.log_execution
async def on_new_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet every new member that joins the main or exec group."""
    msg = update.effective_message
    chat = update.effective_chat

    if chat.id not in (cfg.main_group, cfg.exec_group):
        return

    # * Process all new members concurrently; handles batch joins via invite links
    await asyncio.gather(
        *[_handle_member(m, msg, chat, ctx.bot) for m in msg.new_chat_members],
        return_exceptions=True,
    )


@decorators.log_execution
async def on_left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Announce when a non-bot member leaves the main or exec group."""
    msg = update.effective_message
    chat = update.effective_chat

    if chat.id not in (cfg.main_group, cfg.exec_group):
        return

    member = msg.left_chat_member
    if member and not member.is_bot:
        try:
            await msg.reply_text(
                f"{mention(member.id, member.first_name, member.username)} has left.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("left-member reply_text failed: %s", exc)


@decorators.log_execution
async def on_chat_migration(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Update group records when a basic group migrates to a supergroup.

    Telegram delivers two status updates on migration:
    - ``migrate_to_chat_id`` in the old basic group (bot may no longer have
      write access at that point, so we only log it).
    - ``migrate_from_chat_id`` in the new supergroup, which carries both IDs;
      this is where we perform the DB update.
    """
    msg = update.effective_message
    if not msg:
        return

    if msg.migrate_from_chat_id:
        old_id = msg.migrate_from_chat_id
        new_id = update.effective_chat.id if update.effective_chat else None
        if old_id and new_id and old_id != new_id:
            migrated = await db.groups_db.migrate_group(old_id, new_id)
            if migrated:
                log.info(
                    "Federation group migrated: old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
            else:
                log.debug(
                    "Chat migration received but group was not in federation: "
                    "old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
        return

    if msg.migrate_to_chat_id:
        log.info(
            "Chat migrate_to received: chat_id=%d -> %d "
            "(will be recorded via migrate_from in the supergroup)",
            update.effective_chat.id if update.effective_chat else 0,
            msg.migrate_to_chat_id,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member),
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member),
    MessageHandler(filters.StatusUpdate.MIGRATE, on_chat_migration),
]
