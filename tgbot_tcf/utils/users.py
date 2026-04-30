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
   federated group, kept up to date by :mod:`tgbot_tcf.handlers.membercache`.
3. Numeric fallback ``str(user_id)`` so log copy never breaks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import members_repo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserIdentity:
    user_id: int
    display_name: str
    username: Optional[str] = None

    @property
    def name_with_username(self) -> str:
        if self.username:
            return f"{self.display_name} (@{self.username})"
        return self.display_name


async def resolve_identity(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> UserIdentity:
    """Resolve a user_id to (display_name, username) with graceful fallback."""
    try:
        chat = await context.bot.get_chat(user_id)
        name = chat.first_name or chat.title or None
        username = chat.username
        if name or username:
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
