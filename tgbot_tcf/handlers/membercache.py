# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Per-affiliated-group member tracking handlers (PROMPT Feature 33).

Three update paths feed the cache:

1. :func:`tgbot_tcf.modules.cache_repo.seed_from_admin_list` — called by
   :mod:`.affiliate` on first affiliation.
2. :func:`on_message_in_group` — every message in an active federated
   group upserts its author.
3. :func:`on_chat_member_update` — Telegram chat-member events update
   status transitions (joined / left / promoted / restricted / banned).

The handler stays thin: every write goes through :mod:`.modules.cache_repo`.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..modules import cache_repo
from ..utils.format import safe_first_name

logger = logging.getLogger(__name__)


async def seed_member_cache(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> int:
    """Backwards-compatible re-export so callers can keep importing here."""
    return await cache_repo.seed_from_admin_list(context, chat_id)


async def on_message_in_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Upsert the message author into the cache for active federated groups."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None or user.is_bot:
        return
    chat_id = msg.chat.id
    if not await cache_repo.is_active_group(chat_id):
        return
    await cache_repo.upsert_member(
        chat_id=chat_id,
        user_id=user.id,
        first_name=safe_first_name(user),
        username=user.username,
    )


async def on_chat_member_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Apply per-user chat-member status updates."""
    cm = update.chat_member
    if cm is None:
        return
    chat_id = cm.chat.id
    if not await cache_repo.is_active_group(chat_id):
        return
    new = cm.new_chat_member
    user = new.user
    await cache_repo.upsert_member(
        chat_id=chat_id,
        user_id=user.id,
        first_name=safe_first_name(user),
        username=user.username,
        status=new.status,
    )
