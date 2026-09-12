# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ChatJoinRequestHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_chat, locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.formatter import link, mention
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, Update, User

log = logging.getLogger(__name__)

# * Upper bound for concurrent per-member join handling (batch invite-link
# * joins). Each member costs one harvest write plus ban/mute reads and a
# * Telegram enforcement call; unbounded gather() on a large batch would
# * spike MongoDB pool pressure (pool max 20) and Telegram burst traffic.
# * Matches the fan_out Telegram cap; members beyond the bound wait.
_MAX_CONCURRENT_JOINS: int = 10


async def _in_federation(chat_id: int, *, action: str) -> bool | None:
    """Return True when join events in ``chat_id`` must be enforced.

    Primary groups always qualify; other chats qualify only while their
    connected row is active (cache-backed, negligible latency). Returns
    ``None`` on a lookup outage so the caller stays silent instead of
    enforcing blind or greeting an unverified joiner.
    """
    if cfg.is_primary_group(chat_id):
        return True
    try:
        return await db.groups_db.is_connected(chat_id)
    except Exception as exc:
        log.warning(
            "is_connected check failed for chat=%d on %s: %s", chat_id, action, exc
        )
        return None


async def _auto_demote_for_enforcement(
    bot: Bot, user_id: int, first_name: str, *, trigger: str
) -> None:
    """Best-effort demote of a role-holding target before join enforcement.

    Shared by the ban and mute branches of both join paths
    (``_handle_member`` and ``on_join_request_approved``), which carried
    four identical copies: guarded role lookup, ``Demote.execute``, loud
    logs. A lookup or demote failure never skips enforcement below (the
    DB record already exists; enforcement is the side effect), it only
    logs loudly and proceeds as non-staff.
    """
    try:
        target_role = await db.users_roles.get_effective_role(user_id)
    except Exception:
        log.exception(
            "Role lookup failed on join %s for uid=%d; proceeding anyway",
            trigger,
            user_id,
        )
        return
    if not target_role:
        return
    try:
        await Demote.execute(
            bot,
            user_id,
            first_name or str(user_id),
            target_role,
            0,
            "",
            trigger=trigger,
        )
    except Exception:
        log.exception(
            "Auto-demote on join %s failed for uid=%d role=%s",
            trigger,
            user_id,
            target_role,
        )


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
    locale = await locale_for_chat(chat)

    _, ban, mute = await asyncio.gather(
        db.users_cache.harvest_user_identity(
            member.id,
            member.username,
            member.first_name,
            member.last_name,
        ),
        db.bans_db.get_active_ban(member.id),
        db.mutes_db.get_active_mute(member.id),
        return_exceptions=True,
    )
    # * When an enforcement read fails we cannot prove the joiner is
    # * clean, so the welcome below is skipped: greeting an unverified
    # * user as safe is worse than staying silent until the next event.
    _enforcement_blind = False
    if isinstance(ban, BaseException):
        log.error("get_active_ban failed on join for uid=%d: %s", member.id, ban)
        ban = None
        _enforcement_blind = True
    if isinstance(mute, BaseException):
        log.error("get_active_mute failed on join for uid=%d: %s", member.id, mute)
        mute = None
        _enforcement_blind = True

    if ban:
        # * Best-effort auto-demote keeps the role-vs-state invariant (a
        # * banned user must not hold a federation role); enforcement below
        # * runs regardless because the DB record already exists.
        await _auto_demote_for_enforcement(
            bot, member.id, member.first_name, trigger="ban"
        )
        coros: list = []
        try:
            await bot.ban_chat_member(chat.id, member.id)
        except Exception:
            log.exception(
                "Auto-ban on join failed for uid=%d in chat=%d",
                member.id,
                chat.id,
            )
            return
        if greet:
            notice = t(
                "greeting.notice.banned",
                locale,
                user=Safe(mention(member.id, member.first_name, member.username)),
            )
            ban_id = ban.get("ban_id", "")
            if ban_id:
                notice += t(
                    "greeting.notice.ban_id",
                    locale,
                    ban=str(ban_id),
                )
                if bot.username:
                    appeal_url = appeal_deep_link(bot.username, str(ban_id))
                    notice += t(
                        "greeting.notice.appeal",
                        locale,
                        link=Safe(link("Submit Appeal", appeal_url)),
                    )
            coros.append(
                msg.reply_text(
                    notice,
                    parse_mode="MarkdownV2",
                )
            )
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                log.debug(
                    "Join-auto-ban notice failed for uid=%d: %s", member.id, result
                )
        return

    if mute:
        await _auto_demote_for_enforcement(
            bot, member.id, member.first_name, trigger="mute"
        )
        until = mute.get("until_date")
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

    if greet and not _enforcement_blind:
        await safe_reply(
            msg,
            t(
                "greeting.welcome.body",
                locale,
                user=Safe(mention(member.id, member.first_name, member.username)),
                community=cfg.community_name,
            ),
            log_label=f"Welcome for uid={member.id}",
        )


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
    if msg is None or chat is None:
        return

    is_primary = cfg.is_primary_group(chat.id)

    # * Only act in connected federation groups; skip all other chats.
    if not await _in_federation(chat.id, action="new_member"):
        return

    # * Process all new members concurrently but bounded; handles batch
    # * joins via invite links without exhausting the MongoDB pool or
    # * bursting Telegram traffic. Failures stay per-member via
    # * return_exceptions=True, as before.
    _join_sem = asyncio.Semaphore(_MAX_CONCURRENT_JOINS)

    async def _bounded(m: User) -> None:
        async with _join_sem:
            await _handle_member(m, msg, chat, ctx.bot, greet=is_primary)

    await asyncio.gather(
        *[_bounded(m) for m in msg.new_chat_members],
        return_exceptions=True,
    )


@decorators.log_execution
async def on_join_request_approved(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Re-apply an active federation mute or ban when a join request is approved.

    ``on_join_request`` declines banned users at request time, but an active
    *mute* is not grounds for declining (the user is allowed in, just
    restricted), so it cannot be enforced there. Approving a join request
    does not produce a ``new_chat_members`` service message, so
    ``on_new_member`` never runs for this path either - without this handler
    a muted user could regain full posting rights simply by requesting to
    join and having an admin approve them.

    ``via_join_request`` distinguishes this from a regular invite-link/added
    join (already handled by ``on_new_member``), so no double-enforcement.
    """
    cmu = update.chat_member
    if cmu is None or not cmu.via_join_request:
        return
    if cmu.new_chat_member.status != ChatMemberStatus.MEMBER:
        return

    user = cmu.new_chat_member.user
    if user.is_bot:
        return

    chat = cmu.chat
    if not await _in_federation(chat.id, action="join_request_approved"):
        return

    # * Identity harvest in parallel with mute/ban lookups.
    # * harvest_user_identity skips the DB write when identity is unchanged (L1 hit).
    _, mute, ban = await asyncio.gather(
        db.users_cache.harvest_user_identity(
            user.id, user.username, user.first_name, user.last_name or None
        ),
        db.mutes_db.get_active_mute(user.id),
        db.bans_db.get_active_ban(user.id),
        return_exceptions=True,
    )
    if isinstance(ban, BaseException):
        log.error(
            "get_active_ban failed for uid=%d on join_request_approved in chat=%d: %s",
            user.id,
            chat.id,
            ban,
        )
        ban = None
    if ban:
        # * The request-time decline in on_join_request can be beaten by a
        # * ban created after approval or a failed decline. Enforce here as
        # * well; ban_chat_member on an already-removed user is benign.
        # * Checked before the mute-failure early-return below so a mute-DB
        # * outage cannot disable ban enforcement on this path.
        await _auto_demote_for_enforcement(
            ctx.bot, user.id, user.first_name, trigger="ban"
        )
        try:
            await ctx.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            log.exception(
                "Auto-ban on join_request_approved failed for uid=%d in chat=%d",
                user.id,
                chat.id,
            )
        return
    if isinstance(mute, BaseException):
        log.warning(
            "get_active_mute failed for uid=%d on join_request_approved in chat=%d: %s",
            user.id,
            chat.id,
            mute,
        )
        return
    if not mute:
        return

    await _auto_demote_for_enforcement(
        ctx.bot, user.id, user.first_name, trigger="mute"
    )
    until = mute.get("until_date")
    perms = ChatPermissions(can_send_messages=False)
    try:
        await ctx.bot.restrict_chat_member(
            chat.id, user.id, permissions=perms, until_date=until
        )
        log.info(
            "Re-applied active federation mute on approved join_request for uid=%d in chat=%d",
            user.id,
            chat.id,
        )
    except Exception:
        log.exception(
            "Mute re-apply on join_request_approved failed for uid=%d in chat=%d",
            user.id,
            chat.id,
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
    if not await _in_federation(chat.id, action="join_request"):
        return

    # * Opportunistic identity harvest + ban check in parallel.
    # * harvest_user_identity skips the DB write when identity is unchanged (L1 hit).
    _, ban = await asyncio.gather(
        db.users_cache.harvest_user_identity(
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
    if msg is None or chat is None:
        return

    if not cfg.is_primary_group(chat.id):
        return

    member = msg.left_chat_member
    if member and not member.is_bot:
        await safe_reply(
            msg,
            t(
                "greeting.left.body",
                await locale_for_update(update),
                user=Safe(mention(member.id, member.first_name, member.username)),
            ),
            log_label="left-member",
        )


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
    ChatMemberHandler(on_join_request_approved, ChatMemberHandler.CHAT_MEMBER),
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member),
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member),
    MessageHandler(filters.StatusUpdate.MIGRATE, on_chat_migration),
]
