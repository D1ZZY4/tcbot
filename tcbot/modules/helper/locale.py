# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Render-locale resolution shared by handlers, callbacks, and flows."""

from __future__ import annotations

import asyncio

from tcbot import database as db
from tcbot.modules.helper.context import Ctx
from tcbot.utils.i18n import DEFAULT_LOCALE, is_known_locale, resolve_locale
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


async def _community_locale() -> str | None:
    """Read the community default locale, or None when it is unavailable."""
    try:
        locale = await db.settings_db.get_community_locale()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale community read failed: %s", exc)
        return None
    return locale if isinstance(locale, str) else None


async def _resolve_preference(
    chat_type: str,
    *,
    user_locale: str | None = None,
    group_locale: str | None = None,
) -> str:
    """Resolve one stored preference, then the community default.

    A stored preference that names a catalog locale wins. The community
    tier is read only when the preference is absent or unknown, so the
    ordinary path pays no extra cache read.
    """
    specific = user_locale if chat_type == "private" else group_locale
    if is_known_locale(specific):
        return resolve_locale(
            chat_type=chat_type,
            user_locale=user_locale,
            group_locale=group_locale,
        )
    return resolve_locale(
        chat_type=chat_type,
        user_locale=user_locale,
        group_locale=group_locale,
        community_locale=await _community_locale(),
    )


async def effective_locale(chat_type: object, user_id: int, chat_id: int) -> str:
    """Resolve the locale used to render a message in this chat.

    Only the preference the chat type consumes is read: private chats need
    the user preference, group-like chats need the group row. The other
    read would always be discarded by :func:`resolve_locale`, so skipping
    it halves locale DB reads. A failed preference read falls back to the
    default locale; a successful read that finds nothing consults the
    community default. Resolution never raises. Cancellation propagates.
    """
    candidate: object = getattr(chat_type, "value", chat_type)
    effective_type: str = (
        candidate if isinstance(candidate, str) and candidate else "private"
    )
    if effective_type == "private":
        try:
            user_locale = await db.settings_db.get_user_locale(user_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("locale user read failed for %d: %s", user_id, exc)
            return DEFAULT_LOCALE
        return await _resolve_preference("private", user_locale=user_locale)
    try:
        group_locale = await db.groups_db.get_group_locale(chat_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale group read failed for %d: %s", chat_id, exc)
        return DEFAULT_LOCALE
    return await _resolve_preference(effective_type, group_locale=group_locale)


async def locale_for_update(ctx: Ctx) -> str:
    """Resolve the render locale for one incoming ctx.

    Private chats use the sender's personal locale, groups use the group
    locale, so a shared audience always reads one language. Missing
    chat/user info falls back to the default locale; resolution never
    raises.
    """
    chat = getattr(ctx, "effective_chat", None)
    user = getattr(ctx, "effective_user", None)
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
    (ban notices, appeal updates). The community default is the next tier;
    a failed read falls back to the default locale and never raises.
    """
    try:
        user_locale = await db.settings_db.get_user_locale(user_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale user read failed for %d: %s", user_id, exc)
        return DEFAULT_LOCALE
    return await _resolve_preference("private", user_locale=user_locale)


async def locale_for_chat(chat: object) -> str:
    """Resolve the render locale for a group chat object.

    Used where no Update is available (join/leave events carry chat
    directly). Reads only the group row and then the community default;
    falls back to the default locale. Resolution never raises.
    """
    chat_id = getattr(chat, "id", 0)
    # * This helper reads only the group row, so the preference tier must be
    # * the group tier regardless of a stray private type on the object.
    effective_type = "group"
    try:
        group_locale = await db.groups_db.get_group_locale(chat_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("locale group read failed for %d: %s", chat_id, exc)
        return DEFAULT_LOCALE
    return await _resolve_preference(effective_type, group_locale=group_locale)
