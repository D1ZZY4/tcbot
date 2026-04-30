# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Production-grade identity resolver for federation logs.

The federation needs to display a stable, human-readable name (and ideally
``@username``) for users we ban / unban / appeal — even when:

* The user has blocked the bot or never DM'd it (``get_chat`` returns 400).
* The user changed their first name after the ban was issued.
* The bot is rate-limited at the moment we want to log.

Lookup order:

1. ``context.bot.get_chat(user_id)`` — freshest data, but can fail.
2. ``members_repo.find_latest_for_user`` — last identity we observed in any
   federated group, kept up to date by :mod:`tgbot_tcf.handlers.membercache`
   and by :func:`cache_identity` below whenever an out-of-band lookup
   succeeds.
3. Numeric fallback ``str(user_id)`` so log copy never breaks.

Whenever step 1 succeeds the result is also written back to the member
cache under the global sentinel ``GLOBAL_IDENTITY_CHAT_ID`` so subsequent
identity lookups can short-circuit on the cache without paying for another
``get_chat`` round-trip (and without needing the user to be present in any
particular federated group).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Final

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import members_repo
from ..utils.format import utcnow

logger = logging.getLogger(__name__)

# Sentinel chat_id used to record identity writes that did not happen in
# the context of a real federated group (e.g. an operator typing a numeric
# id into ``/tcban``). Real Telegram chat_ids are either positive (private
# chats / users) or strongly-negative (groups / supergroups), so ``0``
# never collides with a real chat.
GLOBAL_IDENTITY_CHAT_ID: Final[int] = 0


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: int
    display_name: str
    username: str | None = None


async def cache_identity(
    user_id: int,
    *,
    first_name: str | None,
    username: str | None,
    chat_id: int | None = None,
) -> None:
    """Persist a freshly-resolved identity to the member cache.

    ``chat_id`` lets the caller record the write under a real federated
    chat when the lookup happened inside one (the operator's command chat,
    for instance). When ``chat_id`` is ``None`` the write goes under
    :data:`GLOBAL_IDENTITY_CHAT_ID` so out-of-band lookups still benefit
    later identity resolutions.
    """
    if not first_name and not username:
        return
    try:
        await members_repo.upsert(
            chat_id=chat_id if chat_id is not None else GLOBAL_IDENTITY_CHAT_ID,
            user_id=user_id,
            when=utcnow(),
            first_name=first_name,
            username=username,
        )
    except Exception as exc:  # never let a cache write break the caller
        logger.debug("identity cache write for %s failed: %s", user_id, exc)


def schedule_cache_identity(
    user_id: int,
    *,
    first_name: str | None,
    username: str | None,
    chat_id: int | None = None,
) -> None:
    """Fire-and-forget identity cache write so callers stay snappy."""
    if not first_name and not username:
        return
    try:
        asyncio.get_running_loop().create_task(
            cache_identity(
                user_id,
                first_name=first_name,
                username=username,
                chat_id=chat_id,
            )
        )
    except RuntimeError:
        # No running loop (sync context). Skip; caller can await directly.
        pass


async def resolve_identity(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> UserIdentity:
    """Resolve a user_id to (display_name, username) with graceful fallback."""
    try:
        chat = await context.bot.get_chat(user_id)
        name = chat.first_name or chat.title or None
        username = chat.username
        if name or username:
            schedule_cache_identity(
                user_id, first_name=name, username=username
            )
            return UserIdentity(
                user_id=user_id,
                display_name=name or (f"@{username}" if username else str(user_id)),
                username=username,
            )
    except TelegramError as exc:
        logger.debug("get_chat(%s) failed, falling back to cache: %s", user_id, exc)

    cached = await members_repo.find_latest_for_user(user_id)
    if cached:
        name = cached.get("first_name")
        username = cached.get("username")
        if name or username:
            return UserIdentity(
                user_id=user_id,
                display_name=name or (f"@{username}" if username else str(user_id)),
                username=username,
            )

    return UserIdentity(user_id=user_id, display_name=str(user_id), username=None)
