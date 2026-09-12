# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Render-locale resolution shared by handlers, callbacks, and flows."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from tcbot import database as db
from tcbot.utils.i18n import DEFAULT_LOCALE, resolve_locale

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)


def chat_scope(chat_type: str | None) -> str:
    """Map a chat type to the locale scope it reads: user in PM, group otherwise."""
    return "user" if chat_type == "private" else "group"


async def effective_locale(chat_type: str | None, user_id: int, chat_id: int) -> str:
    """Resolve the locale used to render a message in this chat."""
    user_locale, group_locale = await asyncio.gather(
        db.settings_db.get_user_locale(user_id),
        db.groups_db.get_group_locale(chat_id),
        return_exceptions=True,
    )
    if isinstance(user_locale, BaseException):
        log.debug("locale user read failed for %d: %s", user_id, user_locale)
        user_locale = None
    if isinstance(group_locale, BaseException):
        log.debug("locale group read failed for %d: %s", chat_id, group_locale)
        group_locale = None
    return resolve_locale(
        chat_type=chat_type or "private",
        user_locale=user_locale if isinstance(user_locale, str) else None,
        group_locale=group_locale if isinstance(group_locale, str) else None,
    )


async def locale_for_update(update: Update) -> str:
    """Resolve the render locale for one incoming update.

    Private chats use the sender's personal locale, groups use the group
    locale, so a shared audience always reads one language. Missing
    chat/user info falls back to the default locale; resolution never
    raises.
    """
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return DEFAULT_LOCALE
    return await effective_locale(chat.type, user.id, chat.id)
