# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Broadcast business logic.

The :mod:`tgbot_tcf.handlers.broadcast` handler validates input and writes
the audit log; the actual fan-out across every active federated group lives
here so the per-group Telegram failures can be handled in one well-defined
place. The loop runs in parallel under a bounded concurrency limit.
"""
from __future__ import annotations

import asyncio
import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 10


async def broadcast_to_active_groups(
    context: ContextTypes.DEFAULT_TYPE, text: str
) -> tuple[int, int]:
    """Send ``text`` to every active federated group in parallel.

    Groups where the send fails are marked inactive (Telegram has told us
    the bot is no longer reachable). Returns ``(success, failure)``.
    """
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def worker(chat_id: int) -> bool:
        async with sem:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
                return True
            except TelegramError as exc:
                logger.warning("Broadcast to %s failed: %s", chat_id, exc)
                await groups_repo.deactivate(chat_id)
                return False

    chat_ids = [grp["chat_id"] async for grp in groups_repo.iter_active()]
    if not chat_ids:
        return 0, 0
    results = await asyncio.gather(*(worker(cid) for cid in chat_ids))
    success = sum(1 for ok in results if ok)
    return success, len(results) - success
