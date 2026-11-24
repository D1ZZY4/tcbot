# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared permission note and identity harvest for group connection steps."""

from __future__ import annotations

import asyncio

from pyrogram import Client
from pyrogram.types import ChatMember

from tcbot import database as db
from tcbot.modules.helper.context import bot_identity
from tcbot.utils.dispatch import gather_bounded
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.tasks import TaskTracker
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)

# * Telegram added this right recently; it is read from the raw administrator
# * privileges when present so an older server that omits it stays silent.
_WELCOME_PERMISSION: str = "can_send_welcome_messages"

# * Owner of the in-flight admin-identity harvests.
harvest_tasks = TaskTracker("admin harvest")


async def welcome_permission_note(bot: Client, chat_id: int, locale: str | None) -> str:
    """Return an operator note when the bot lacks the native welcome right.

    The right is exposed on the raw administrator privileges, but there is no
    method that sets the native welcome message itself. The bot can therefore
    audit the grant and tell the owner how to enable it, but it cannot create
    the message. A server that omits the field is not reported as a refusal.
    """
    try:
        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            member = await bot.get_chat_member(chat_id, (await bot_identity(bot)).id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Welcome permission check failed for chat=%d: %s", chat_id, exc)
        return ""
    privileges = getattr(member, "privileges", None)
    granted = getattr(privileges, _WELCOME_PERMISSION, None)
    if granted is False:
        return "\n\n" + t("connecting.state.welcome_perm_missing", locale, plain=True)
    return ""


async def harvest_admin_identities(chat_id: int, admins: list[ChatMember]) -> None:
    """Persist identity data for every admin using change-detection writes."""
    coros = []
    for member in admins:
        user = getattr(member, "user", None)
        if user is None or user.is_bot or not user.first_name:
            continue
        coros.append(
            db.users_cache.harvest_user_identity(
                user.id, user.username, user.first_name, user.last_name
            )
        )
    if not coros:
        return
    results = await gather_bounded(coros)
    errors = sum(1 for r in results if isinstance(r, BaseException))
    if errors:
        log.debug(
            "Admin identity harvest for chat=%d: %d/%d writes failed",
            chat_id,
            errors,
            len(coros),
        )
    else:
        log.debug(
            "Admin identity harvest for chat=%d: %d identities cached",
            chat_id,
            len(coros),
        )
