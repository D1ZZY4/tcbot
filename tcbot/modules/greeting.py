# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

import asyncio
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
from tcbot.modules.helper.messages import safe_reply
from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.modules.helper.pipelines.demote_flow import demote_before_enforcement
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import link, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, Update, User

log = get_logger(__name__)

# * Upper bound for concurrent per-member join handling (batch invite-link
# * joins). Each member costs one harvest write plus ban/mute reads and a
# * Telegram enforcement call; unbounded gather() on a large batch would
# * spike MongoDB pool pressure (pool max 20) and Telegram burst traffic.
# * Matches the fan_out Telegram cap; members beyond the bound wait.
_MAX_CONCURRENT_JOINS: int = 10

# * One global bound for ALL concurrent join updates (not per-update): with
# * concurrent_updates(True) each new-member callback would otherwise get its
# * own Semaphore(10), making the effective Telegram+Mongo concurrency N*10
# * with no ceiling.
_join_sem = asyncio.Semaphore(_MAX_CONCURRENT_JOINS)


async def _in_federation(chat_id: int, *, action: str) -> bool | None:
    """Return True when join events in ``chat_id`` must be enforced.

    Primary groups always qualify; other chats qualify only while their
    connected row is active, read directly so a disconnect in another
    process stops join enforcement at once instead of lingering for the
    connection cache TTL. Returns ``None`` on a lookup outage so the
    caller stays silent instead of enforcing blind or greeting an
    unverified joiner.
    """
    if cfg.is_primary_group(chat_id):
        return True
    try:
        return await db.groups_db.is_connected(chat_id, fresh=True)
    except Exception as exc:
        log.warning(
            "is_connected check failed for chat=%d on %s: %s", chat_id, action, exc
        )
        return None


async def _handle_member(
    member: User,
    msg: Message,
    chat: Chat,
    bot: Bot,
    locale: str,
    *,
    greet: bool = True,
) -> None:
    """Process a single new member: cache, ban-check, then enforce ban or greet.

    When ``greet=False`` (non-primary connected groups) the ban is still enforced
    silently but no welcome or removal-notice message is posted, avoiding noise
    in secondary groups. When ``greet=True`` both messages are sent.

    ``locale`` is resolved once by the caller: batch joins share one chat, so
    resolving it per member repeats the same read N times.
    """
    if member.is_bot:
        return

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
    # ! CRITICAL: a cancelled read must propagate, never degrade into a
    # ! clean greet: shutdown would otherwise welcome a banned joiner.
    throw_if_cancelled((ban, mute))
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
        # * Best-effort demote keeps the role-vs-state invariant (a
        # * banned user must not hold a federation role); enforcement below
        # * runs regardless because the DB record already exists.
        await demote_before_enforcement(
            bot, member.id, member.first_name, trigger="ban"
        )
        try:
            await asyncio.wait_for(
                bot.ban_chat_member(chat.id, member.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except Exception:
            log.exception(
                "Ban on join failed for uid=%d in chat=%d",
                member.id,
                chat.id,
            )
            return
        if greet:
            notice = t(
                "greeting.notice.banned",
                locale,
                user=Safe(user_ref(member.id, member.first_name, member.username)),
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
                        link=Safe(
                            link(
                                t("button.submit_appeal", locale, plain=True),
                                appeal_url,
                            )
                        ),
                    )
            try:
                await msg.reply_text(notice, parse_mode="MarkdownV2")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("Join ban notice failed for uid=%d: %s", member.id, exc)
        return

    if mute:
        await demote_before_enforcement(
            bot, member.id, member.first_name, trigger="mute"
        )
        until = mute.get("until_date")
        perms = ChatPermissions(can_send_messages=False)
        try:
            await asyncio.wait_for(
                bot.restrict_chat_member(
                    chat.id, member.id, permissions=perms, until_date=until
                ),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
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
                user=Safe(user_ref(member.id, member.first_name, member.username)),
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

    # * One chat, one locale: resolve once for the whole batch below.
    locale = await locale_for_chat(chat)

    # * Process all new members concurrently but bounded; handles batch
    # * joins via invite links without exhausting the MongoDB pool or
    # * bursting Telegram traffic. Failures stay per-member via
    # * return_exceptions=True, as before.
    # * Shared global semaphore (module-level _join_sem); do not re-create a
    # * per-update Semaphore here.

    async def _bounded(m: User) -> None:
        async with _join_sem:
            await _handle_member(m, msg, chat, ctx.bot, locale, greet=is_primary)

    join_results = await asyncio.gather(
        *[_bounded(m) for m in msg.new_chat_members],
        return_exceptions=True,
    )
    throw_if_cancelled(join_results)


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
    # ! CRITICAL: cancellation must propagate before any enforcement
    # ! decision; coercing it into ban=None skips the ban below.
    throw_if_cancelled((mute, ban))
    if isinstance(ban, BaseException):
        log.error(
            "get_active_ban failed for uid=%d on join_request_approved in chat=%d: %s",
            user.id,
            chat.id,
            ban,
        )
        # * Fail closed: suppress welcome and mute enforcement until ban
        # * state is proven clean; /tcsync heals on next sweep.
        return
    if ban:
        # * The request-time decline in on_join_request can be beaten by a
        # * ban created after approval or a failed decline. Enforce here as
        # * well; ban_chat_member on an already-removed user is benign.
        # * Checked before the mute-failure early-return below so a mute-DB
        # * outage cannot disable ban enforcement on this path.
        await demote_before_enforcement(
            ctx.bot, user.id, user.first_name, trigger="ban"
        )
        try:
            await asyncio.wait_for(
                ctx.bot.ban_chat_member(chat.id, user.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except Exception:
            log.exception(
                "Ban on join_request_approved failed for uid=%d in chat=%d",
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

    await demote_before_enforcement(ctx.bot, user.id, user.first_name, trigger="mute")
    until = mute.get("until_date")
    perms = ChatPermissions(can_send_messages=False)
    try:
        await asyncio.wait_for(
            ctx.bot.restrict_chat_member(
                chat.id, user.id, permissions=perms, until_date=until
            ),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
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
    throw_if_cancelled((ban,))
    if isinstance(ban, BaseException):
        log.error(
            "get_active_ban failed for uid=%d on join_request in chat=%d: %s",
            user.id,
            chat.id,
            ban,
        )
        # * Fail closed on outage: decline rather than allow a possibly
        # * banned user to enter until state is proven clean.
        try:
            await ctx.bot.decline_chat_join_request(chat.id, user.id)
        except Exception as exc:
            log.warning(
                "Failed to decline join request for uid=%d in chat=%d: %s",
                user.id,
                chat.id,
                exc,
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
                user=Safe(user_ref(member.id, member.first_name, member.username)),
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
            (
                migrated,
                _warns_migrated,
                _kicks_migrated,
                _mutes_migrated,
            ) = await asyncio.gather(
                db.groups_db.migrate_group(old_id, new_id),
                db.warns_db.migrate_records(old_id, new_id),
                db.kicks_db.migrate_records(old_id, new_id),
                db.mutes_db.migrate_records(old_id, new_id),
                return_exceptions=True,
            )
            throw_if_cancelled(
                (migrated, _warns_migrated, _kicks_migrated, _mutes_migrated)
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
            if isinstance(_kicks_migrated, BaseException):
                log.error(
                    "kicks_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _kicks_migrated,
                )
            if isinstance(_mutes_migrated, BaseException):
                log.error(
                    "mutes_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _mutes_migrated,
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
# connect.py. That single handler covers bot-added/promoted (join prompt,
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
