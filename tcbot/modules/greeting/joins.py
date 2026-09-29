# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join enforcement: member handling and the new-member entry point."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import ChatPermissions
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_chat
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import link, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

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

    # * Process all new members concurrently but bounded; handles batch
    # * joins via invite links without exhausting the MongoDB pool or
    # * bursting Telegram traffic. Failures stay per-member via
    # * return_exceptions=True, as before.
    # * Shared global semaphore (module-level _join_sem); do not re-create a
    # * per-update Semaphore here.

    # * Resolved through the package namespace so patching
    # * greeting._handle_member stays effective after the package split.
    from tcbot.modules import greeting as _pkg  # noqa: PLC0415

    async def _bounded(m: User) -> None:
        async with _join_sem:
            await _pkg._handle_member(m, msg, chat, ctx.bot, greet=is_primary)

    await asyncio.gather(
        *[_bounded(m) for m in msg.new_chat_members],
        return_exceptions=True,
    )
