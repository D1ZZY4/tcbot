# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Member-cache helpers (PROMPT Feature 33).

This module bridges the database-only writes in :mod:`tgbot_tcf.database.members`
with the Telegram API call needed to seed a freshly-affiliated group from
its admin list. Keeping the seeding logic out of the handler keeps the
member-cache write rules in a single, easy-to-audit place.
"""
from __future__ import annotations

import asyncio
import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo, members_repo
from ..utils.format import safe_first_name, utcnow

logger = logging.getLogger(__name__)


async def is_active_group(chat_id: int) -> bool:
    """Return ``True`` if ``chat_id`` is an active federated group."""
    return await groups_repo.find_active(chat_id) is not None


async def upsert_member(
    *,
    chat_id: int,
    user_id: int,
    first_name: str | None = None,
    username: str | None = None,
    status: str | None = None,
) -> None:
    """Single entry point for all member-cache writes."""
    await members_repo.upsert(
        chat_id=chat_id,
        user_id=user_id,
        when=utcnow(),
        first_name=first_name,
        username=username,
        status=status,
    )


async def seed_from_admin_list(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> int:
    """Seed the cache for a freshly-affiliated group; returns count seeded.

    Telegram's Bot API does not allow listing every member, so the best we
    can do at affiliation time is snapshot the administrators. Subsequent
    messages and chat-member events fill in the rest.
    """
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except TelegramError as exc:
        logger.warning("Could not seed member cache for %s: %s", chat_id, exc)
        return 0
    if not admins:
        return 0
    await asyncio.gather(
        *(
            upsert_member(
                chat_id=chat_id,
                user_id=cm.user.id,
                first_name=safe_first_name(cm.user),
                username=cm.user.username,
                status=cm.status,
            )
            for cm in admins
        )
    )
    return len(admins)
