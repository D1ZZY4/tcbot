# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Render-locale resolution shared by handlers, callbacks, and flows."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import database as db
from tcbot.utils.i18n import DEFAULT_LOCALE, resolve_locale
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


async def _user_locale(user_id: int) -> str | None:
    """Read the stored user locale, or None when it is unavailable."""
    try:
        locale = await db.settings_db.get_user_locale(user_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale user read failed for %d: %s", user_id, exc)
        return None
    return locale if isinstance(locale, str) else None


async def _group_locale(chat_id: int, chat_type: str) -> str:
    """Resolve the locale a group-like chat renders in."""
    try:
        locale = await db.groups_db.get_group_locale(chat_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale group read failed for %d: %s", chat_id, exc)
        locale = None
    return resolve_locale(
        chat_type=chat_type,
        group_locale=locale if isinstance(locale, str) else None,
    )


async def effective_locale(chat_type: str | None, user_id: int, chat_id: int) -> str:
    """Resolve the locale used to render a message in this chat.

    Only the locale the chat type consumes is read: private chats need the
    user preference, group-like chats need the group row. The other read
    would always be discarded by :func:`resolve_locale`, so skipping it
    halves locale DB reads. Resolution never raises; a failed read falls
    back to the default locale. Cancellation propagates.
    """
    effective_type = chat_type or "private"
    if effective_type == "private":
        return resolve_locale(
            chat_type="private",
            user_locale=await _user_locale(user_id),
        )
    return await _group_locale(chat_id, effective_type)


async def locale_for_update(update: Update) -> str:
    """Resolve the render locale for one incoming update.

    Private chats use the sender's personal locale, groups use the group
    locale, so a shared audience always reads one language. Missing
    chat/user info falls back to the default locale; resolution never
    raises.
    """
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if chat is None or user is None:
        return DEFAULT_LOCALE
    return await effective_locale(
        getattr(chat, "type", None),
        getattr(user, "id", 0),
        getattr(chat, "id", 0),
    )


async def locale_for_user(user_id: int) -> str:
    """Resolve the personal locale for a direct message to one user.

    Used for PMs where the audience is a single user rather than a chat
    (ban notices, appeal updates). Falls back to the default locale;
    resolution never raises.
    """
    return resolve_locale(
        chat_type="private",
        user_locale=await _user_locale(user_id),
    )


async def locale_for_chat(chat: object) -> str:
    """Resolve the render locale for a group chat object.

    Used where no Update is available (join/leave events carry chat
    directly). Reads only the group row; falls back to the default
    locale. Resolution never raises.
    """
    chat_id = getattr(chat, "id", 0)
    chat_type = getattr(chat, "type", None)
    return await _group_locale(
        chat_id,
        chat_type if isinstance(chat_type, str) else "group",
    )
