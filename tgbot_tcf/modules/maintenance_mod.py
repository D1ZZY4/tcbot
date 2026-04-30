# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Maintenance loops: leave-all and cleanup-of-inaccessible groups.

Both routines fan out across every active federated group in parallel under
a bounded concurrency limit, perform a per-group Telegram action (leave or
membership probe), update the ``federated_groups`` collection, and post a
structured log entry per change. Returning the counters lets the calling
handler reply with a single human-friendly summary.
"""
from __future__ import annotations

import asyncio
import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo
from ..utils.logger import log_to_channel
from . import log_templates

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 10


async def leave_all_active_groups(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    by_user_id: int,
    by_user_name: str,
) -> tuple[int, int]:
    """Leave every active federated group in parallel. Returns ``(success, failure)``."""
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def worker(grp: dict) -> bool:
        chat_id = grp["chat_id"]
        title = grp.get("title") or str(chat_id)
        async with sem:
            try:
                await context.bot.leave_chat(chat_id)
            except TelegramError as exc:
                logger.warning("Leave %s failed: %s", chat_id, exc)
                return False
            await groups_repo.deactivate(chat_id)
            await log_to_channel(
                context,
                log_templates.group_disaffiliated(
                    title=title,
                    chat_id=chat_id,
                    by_user_id=by_user_id,
                    by_user_name=by_user_name,
                ),
            )
            return True

    groups = await groups_repo.list_active()
    if not groups:
        return 0, 0
    results = await asyncio.gather(*(worker(g) for g in groups))
    success = sum(1 for ok in results if ok)
    return success, len(results) - success


async def cleanup_inaccessible_groups(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    by_user_id: int,
    by_user_name: str,
) -> int:
    """Mark groups inactive when the bot is no longer a member. Returns count."""
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def worker(grp: dict) -> bool:
        chat_id = grp["chat_id"]
        title = grp.get("title") or str(chat_id)
        async with sem:
            accessible = True
            try:
                me = await context.bot.get_chat_member(chat_id, context.bot.id)
                if me.status in ("left", "kicked"):
                    accessible = False
            except TelegramError:
                accessible = False
            if accessible:
                return False
            await groups_repo.deactivate(chat_id)
            await log_to_channel(
                context,
                log_templates.group_disaffiliated(
                    title=title,
                    chat_id=chat_id,
                    by_user_id=by_user_id,
                    by_user_name=by_user_name,
                ),
            )
            return True

    groups = await groups_repo.list_active()
    if not groups:
        return 0
    results = await asyncio.gather(*(worker(g) for g in groups))
    return sum(1 for ok in results if ok)
