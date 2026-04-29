# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Maintenance loops: leave-all and cleanup-of-inaccessible groups.

Both routines iterate over every active federated group, perform a per-group
Telegram action (leave or membership probe), update the ``federated_groups``
collection, and post a structured log entry per change. Returning the
counters lets the calling handler reply with a single human-friendly summary.
"""
from __future__ import annotations

import logging
from typing import Tuple

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo
from ..utils.logger import log_to_channel
from . import log_templates

logger = logging.getLogger(__name__)


async def leave_all_active_groups(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    by_user_id: int,
    by_user_name: str,
) -> Tuple[int, int]:
    """Leave every active federated group. Returns ``(success, failure)``."""
    success = 0
    failure = 0
    groups = await groups_repo.list_active()
    for g in groups:
        chat_id = g["chat_id"]
        title = g.get("title") or str(chat_id)
        try:
            await context.bot.leave_chat(chat_id)
            await groups_repo.deactivate(chat_id)
            success += 1
            await log_to_channel(
                context,
                log_templates.group_disaffiliated(
                    title=title,
                    chat_id=chat_id,
                    by_user_id=by_user_id,
                    by_user_name=by_user_name,
                ),
            )
        except TelegramError as exc:
            failure += 1
            logger.warning("Leave %s failed: %s", chat_id, exc)
    return success, failure


async def cleanup_inaccessible_groups(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    by_user_id: int,
    by_user_name: str,
) -> int:
    """Mark groups inactive when the bot is no longer a member. Returns count."""
    cleaned = 0
    groups = await groups_repo.list_active()
    for g in groups:
        chat_id = g["chat_id"]
        title = g.get("title") or str(chat_id)
        accessible = True
        try:
            me = await context.bot.get_chat_member(chat_id, context.bot.id)
            if me.status in ("left", "kicked"):
                accessible = False
        except TelegramError:
            accessible = False

        if not accessible:
            await groups_repo.deactivate(chat_id)
            cleaned += 1
            await log_to_channel(
                context,
                log_templates.group_disaffiliated(
                    title=title,
                    chat_id=chat_id,
                    by_user_id=by_user_id,
                    by_user_name=by_user_name,
                ),
            )
    return cleaned
