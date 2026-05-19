# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Throttled multi-group dispatcher

fan_out(coros) - run many coroutines concurrently, bounded by a semaphore so
the bot never fires more than MAX_CONCURRENT Telegram API calls simultaneously.

Telegram's documented hard limits (per bot):
    • 30 messages / second across all chats combined
    • 1 message  / second per individual chat
Capping at 10 concurrent calls keeps us well inside those ceilings even on
large federations, while being orders of magnitude faster than a sequential loop.
All exceptions are captured in-place - a single failed group never blocks the rest.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)


# * Telegram allows 30 msg/s globally; 10 concurrent is safe and fast.
_MAX_CONCURRENT: int = 10


# ──────────────── Throttled Multi-Group Dispatcher ──────────────── #

async def fan_out(
    coros: list[Coroutine[Any, Any, Any]],
    *,
    max_concurrent: int = _MAX_CONCURRENT,
) -> list[Any | BaseException]:
    """
    Run a list of coroutines concurrently with concurrency limiting
    * Uses semaphore to ensure no more than max_concurrent tasks run at once
    * Returns list matching input order: either result or captured exception
    * Never raises exceptions - all errors are captured and returned
    * Critical for bulk operations that would otherwise hit Telegram rate limits
    
    Usage::
        results = await fan_out(
            [bot.ban_chat_member(grp["chat_id"], uid) for grp in groups]
        )
        failed = sum(1 for r in results if isinstance(r, BaseException))
    """
    if not coros:
        return []

    sem = asyncio.Semaphore(max_concurrent)

    async def _slot(coro: Coroutine[Any, Any, Any]) -> Any | BaseException:
        """Internal wrapper to execute a single coroutine with semaphore"""
        async with sem:
            try:
                return await coro
            except Exception as exc:
                log.debug("Coroutine failed in fan_out: %s", exc)
                return exc

    return list(await asyncio.gather(*(_slot(c) for c in coros)))
