# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import ChatPermissions
from telegram.ext import (
    ChatJoinRequestHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.formatter import esc, mention

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, Update, User

log = logging.getLogger(__name__)


# ───────────────────────── Member Handlers ──────────────────────── #


async def _handle_member(
    member: User, msg: Message, chat: Chat, bot: Bot, *, greet: bool = True
) -> None:
    """Process a single new member: cache, ban-check, then enforce ban or greet.

    When ``greet=False`` (non-primary connected groups) the ban is still enforced
    silently but no welcome or removal-notice message is posted, avoiding noise
    in secondary groups. When ``greet=True`` both messages are sent.
    """
    if member.is_bot:
        return

    _, ban, mute = await asyncio.gather(
        db.users_cache.upsert_user_if_changed(
            member.id,
            member.username,
            member.first_name,
            member.last_name,
        ),
        db.bans_db.get_active_ban(member.id),
        db.mutes_db.get_active_mute(member.id),
        return_exceptions=True,
    )
    if isinstance(ban, BaseException):
        log.error("get_active_ban failed on join for uid=%d: %s", member.id, ban)
        ban = None
    if isinstance(mute, BaseException):
        log.error("get_active_mute failed on join for uid=%d: %s", member.id, mute)
        mute = None

    if ban:
        coros: list = [bot.ban_chat_member(chat.id, member.id)]
        if greet:
            coros.append(
                msg.reply_text(
                    f"{mention(member.id, member.first_name, member.username)}"
                    " is federation-banned and was removed.",
                    parse_mode="HTML",
                )
            )
        results = await asyncio.gather(*coros, return_exceptions=True)
        if isinstance(results[0], BaseException):
            log.error(
                "Auto-ban on join failed for uid=%d in chat=%d: %s",
                member.id,
                chat.id,
                results[0],
            )
        return

    if mute:
        until = mute.get("until_date") if mute else None
        perms = ChatPermissions(can_send_messages=False)
        try:
            await bot.restrict_chat_member(
                chat.id, member.id, permissions=perms, until_date=until
            )
            log.info(
                "Re-applied active federation mute for uid=%d in chat=%d",
                member.id,
                chat.id,
            )
        except Exception:
            log.exception(
                "Mute re-apply on join failed for uid=%d in chat=%d",
                member.id,
                chat.id,
            )

    if greet:
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
    """Enforce bans on new members in all connected groups; greet only in primary groups.

    Previously this handler returned early for chats that were not the primary
    or exec group, meaning a federation-banned user who joined a secondary
    connected group would not be removed. This version checks ``is_connected``
    for non-primary chats (the result is L1+L2 cached) and runs
    ``_handle_member`` with ``greet=False`` for them so bans are enforced
    everywhere without producing welcome-message noise in secondary groups.
    """
    msg = update.effective_message
    chat = update.effective_chat

    is_primary = chat.id in (cfg.main_group, cfg.exec_group)

    if not is_primary:
        # * Only act in connected federation groups; skip all other chats.
        # * is_connected is cache-backed so this adds negligible latency.
        try:
            connected = await db.groups_db.is_connected(chat.id)
        except Exception as exc:
            log.warning(
                "is_connected check failed for chat=%d on new_member: %s", chat.id, exc
            )
            return
        if not connected:
            return

    # * Process all new members concurrently; handles batch joins via invite links
    await asyncio.gather(
        *[
            _handle_member(m, msg, chat, ctx.bot, greet=is_primary)
            for m in msg.new_chat_members
        ],
        return_exceptions=True,
    )


@decorators.log_execution
async def on_join_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Decline join requests from federation-banned users in connected groups.

    When a group has join-request mode enabled (invite links require admin
    approval), Telegram delivers a ``ChatJoinRequest`` update instead of a
    ``new_chat_member`` status. Without this handler a banned user could
    bypass enforcement by requesting to join and waiting for an admin (or an
    auto-approve bot) to accept them.

    The handler declines the request silently when the user has an active
    federation ban. Non-banned users are left for the normal approval flow.
    Also opportunistically caches the requesting user's identity.
    """
    request = update.chat_join_request
    if request is None:
        return

    user = request.from_user
    if user is None or user.is_bot:
        return

    chat = request.chat
    is_primary = chat.id in (cfg.main_group, cfg.exec_group)

    if not is_primary:
        try:
            connected = await db.groups_db.is_connected(chat.id)
        except Exception as exc:
            log.warning(
                "is_connected check failed for chat=%d on join_request: %s",
                chat.id,
                exc,
            )
            return
        if not connected:
            return

    # * Opportunistic identity harvest + ban check in parallel.
    # * upsert_user_if_changed skips the DB write when identity is unchanged (L1 hit).
    _, ban = await asyncio.gather(
        db.users_cache.upsert_user_if_changed(
            user.id, user.username, user.first_name, user.last_name or None
        ),
        db.bans_db.get_active_ban(user.id),
        return_exceptions=True,
    )
    if isinstance(ban, BaseException):
        log.warning(
            "get_active_ban failed for uid=%d on join_request in chat=%d: %s",
            user.id,
            chat.id,
            ban,
        )
        return

    if not ban:
        return  # not banned; let the normal approval flow proceed

    try:
        await ctx.bot.decline_chat_join_request(chat.id, user.id)
        log.info(
            "Declined join request from federation-banned user uid=%d in chat=%d",
            user.id,
            chat.id,
        )
    except Exception as exc:
        log.warning(
            "Failed to decline join request for uid=%d in chat=%d: %s",
            user.id,
            chat.id,
            exc,
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
            migrated, _warns_migrated = await asyncio.gather(
                db.groups_db.migrate_group(old_id, new_id),
                db.warns_db.migrate_records(old_id, new_id),
                return_exceptions=True,
            )
            if isinstance(migrated, BaseException):
                log.error(
                    "groups_db.migrate_group failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    migrated,
                )
                migrated = False
            if isinstance(_warns_migrated, BaseException):
                log.error(
                    "warns_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _warns_migrated,
                )
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

# NOTE: The bot's own chat-member updates (MY_CHAT_MEMBER) are handled
# exclusively by connected_flow.connection.on_bot_added, registered in
# connecting.py. That single handler covers bot-added/promoted (join prompt,
# pending completion), bot-demoted (admin-rights-lost warning to mod channel),
# and bot-removed/kicked (federation group auto-deactivation). No second
# ChatMemberHandler is registered here to avoid PTB group-0 shadowing.

__handlers__ = [
    ChatJoinRequestHandler(on_join_request),
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member),
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member),
    MessageHandler(filters.StatusUpdate.MIGRATE, on_chat_migration),
]
