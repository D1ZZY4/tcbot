# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join-request decline and approval enforcement."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.greeting.joins import (
    _auto_demote_for_enforcement,
    _in_federation,
)
from tcbot.modules.helper import decorators
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


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
    throw_if_cancelled((ban,))
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
