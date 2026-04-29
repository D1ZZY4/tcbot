# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group affiliation business logic.

The handler in :mod:`tgbot_tcf.handlers.affiliate` is responsible for
parsing Telegram updates and replying with the correct copy. The actual
work — checking permissions, recording pending requests, completing
affiliation, seeding the member cache and writing to the log channel —
lives here.
"""
from __future__ import annotations

import logging
from typing import Final, Optional, Tuple

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import INITIAL_OWNER_ID
from ..database import admins_repo, groups_repo, joins_repo
from ..utils.format import utcnow
from ..utils.logger import log_to_channel
from . import cache_repo, log_templates

logger = logging.getLogger(__name__)

REQUIRED_PERMS: Final[Tuple[str, str, str]] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)
"""Admin permissions the bot must hold inside an affiliated group."""


def has_required_perms(member_obj) -> bool:
    """Return ``True`` if a ``ChatMember`` object holds all required perms."""
    if member_obj.status not in ("administrator", "creator"):
        return False
    return all(getattr(member_obj, p, False) for p in REQUIRED_PERMS)


async def bot_has_required_perms(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> bool:
    """Check the bot itself, fetching its current chat-member object."""
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as exc:
        logger.warning("Permission check failed in %s: %s", chat_id, exc)
        return False
    return has_required_perms(me)


async def is_active(chat_id: int) -> bool:
    """Return ``True`` if ``chat_id`` is currently a federated group."""
    return await groups_repo.find_active(chat_id) is not None


async def record_pending(
    *, chat_id: int, title: str, requested_by: int, notice_message_id: Optional[int]
) -> None:
    """Park an affiliation request waiting for permissions to be granted."""
    await joins_repo.upsert(
        chat_id=chat_id,
        title=title,
        requested_by=requested_by,
        requested_at=utcnow(),
        notice_message_id=notice_message_id,
    )


async def pop_pending(chat_id: int) -> Optional[dict]:
    """Return-and-clear a pending request for ``chat_id`` (or ``None``)."""
    pending = await joins_repo.get(chat_id)
    if pending:
        await joins_repo.delete(chat_id)
    return pending


async def finalize_affiliation(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    title: str,
    added_by: int,
    added_by_name: str,
) -> None:
    """Insert/refresh the federated group, seed members, and log the event."""
    await groups_repo.upsert_active(
        chat_id=chat_id,
        title=title,
        added_by=added_by,
        added_date=utcnow(),
    )
    await joins_repo.delete(chat_id)
    await admins_repo.ensure_owner_seed(INITIAL_OWNER_ID)
    seeded = await cache_repo.seed_from_admin_list(context, chat_id)
    logger.info(
        "Seeded %d members for newly affiliated chat %s", seeded, chat_id
    )
    await log_to_channel(
        context,
        log_templates.new_affiliated_group(
            title=title,
            chat_id=chat_id,
            owner_id=added_by,
            owner_name=added_by_name,
        ),
    )


async def deactivate_group(chat_id: int) -> None:
    """Mark a group inactive and forget any pending join."""
    await groups_repo.deactivate(chat_id)
    await joins_repo.delete(chat_id)
