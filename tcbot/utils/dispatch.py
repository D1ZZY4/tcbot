# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Throttled multi-group dispatcher: runs coroutines concurrently with a semaphore cap."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

log = logging.getLogger(__name__)

# * Telegram allows 30 msg/s globally; 10 concurrent is safe and fast.
_MAX_CONCURRENT: int = 10


# ──────────────── Throttled Multi-Group Dispatcher ──────────────── #


async def fan_out[T](
    coros: Sequence[Awaitable[T]],
    *,
    max_concurrent: int = _MAX_CONCURRENT,
) -> list[T | BaseException]:
    """Run coros concurrently up to max_concurrent at once; never raises."""
    if not coros:
        return []

    sem = asyncio.Semaphore(max_concurrent)

    async def _slot(coro: Awaitable[T]) -> T | BaseException:
        async with sem:
            try:
                return await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("Coroutine failed in fan_out: %s", exc)
                return exc

    return list(
        await asyncio.gather(*(_slot(c) for c in coros), return_exceptions=True)
    )


def count_errors(results: Sequence[object]) -> int:
    """Return the number of BaseException items in a fan_out result list."""
    return sum(1 for r in results if isinstance(r, BaseException))
