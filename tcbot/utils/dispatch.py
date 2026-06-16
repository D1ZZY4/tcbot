# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Throttled multi-group dispatcher: runs coroutines concurrently with a semaphore cap.

Wraps fan_out slots with the Telegram circuit breaker so that repeated
network timeouts do not saturate the semaphore pool with stalled tasks.
Only ``telegram.error.TimedOut`` and ``telegram.error.NetworkError`` are
counted against the circuit; expected API refusals (403, 400) are not.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.error import NetworkError, TimedOut

from tcbot.utils import circuit_breaker as _cb

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
    """Run coros concurrently up to max_concurrent at once; never raises.

    Integrates the Telegram circuit breaker: slots that run while the circuit
    is OPEN are skipped immediately (returning a ``CircuitOpenError``) instead
    of firing a Telegram request that will time out.  TimedOut and
    NetworkError results trip the circuit; all other exceptions (403, 400,
    etc.) are treated as expected API refusals and do not affect the circuit.
    """
    if not coros:
        return []

    sem = asyncio.Semaphore(max_concurrent)

    async def _slot(coro: Awaitable[T]) -> T | BaseException:
        async with sem:
            if _cb.telegram.is_open:
                log.warning(
                    "fan_out: Telegram circuit OPEN; skipping slot to avoid timeout."
                )
                return _cb.CircuitOpenError("Telegram circuit is OPEN; call skipped.")
            try:
                result = await coro
                _cb.telegram.record_success()
                return result
            except (TimedOut, NetworkError) as exc:
                _cb.telegram.record_failure()
                log.debug("fan_out: network error (counted against circuit): %s", exc)
                return exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug(
                    "fan_out: coroutine failed (not counted against circuit): %s", exc
                )
                return exc

    return list(
        await asyncio.gather(*(_slot(c) for c in coros), return_exceptions=True)
    )


def count_errors(results: Sequence[object]) -> int:
    """Return the number of BaseException items in a fan_out result list."""
    return sum(1 for r in results if isinstance(r, BaseException))
