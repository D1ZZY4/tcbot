# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ordered Redis mutation queue shared by TwoLevelCache instances."""

from __future__ import annotations

import asyncio
from typing import Any

import tcbot.database.redis_client as _redis_mod
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * Strong refs to in-flight tasks; prevents GC before completion.
_redis_bg_tasks: set[asyncio.Task[None]] = set()
# * FIFO order per (prefix, loop); asyncio tasks cannot await across loops.
_redis_tails: dict[tuple[str, asyncio.AbstractEventLoop], asyncio.Task[None]] = {}
# * Past this queued depth per (prefix, loop) droppable ops drop with a
# * warning. L2 is a TTL hint layer, so a drop only extends staleness to
# * the key TTL while an unbounded queue would stall revocation paths.
_REDIS_MAX_PENDING: int = 200
_redis_pending: dict[tuple[str, asyncio.AbstractEventLoop], int] = {}
_redis_drop_warned: set[tuple[str, asyncio.AbstractEventLoop]] = set()
# * Grace window for draining background mutations before the pool closes.
_DRAIN_TIMEOUT_S: float = 5.0
# * Ceiling for one clear_all wait; the sweep keeps running past it so a
# * dead-Redis backlog delays the caller briefly instead of stalling it.
_CLEAR_ALL_TIMEOUT_S: float = 10.0
# * Upper bound for one L2 read on the hot path; a timeout falls through
# * to the DB fetch, so correctness never depends on Redis.
_REDIS_GET_TIMEOUT_S: float = 1.0
# * Per-op ceiling for fire-and-forget L2 writes; abandonment only delays
# * an L2 hint because mutations serialize FIFO per prefix.
_REDIS_WRITE_TIMEOUT_S: float = 2.0


def _release_redis_slot(tail_key: tuple[str, asyncio.AbstractEventLoop]) -> None:
    """Decrement the queued-mutation depth and re-arm the drop warning."""
    remaining = _redis_pending.get(tail_key, 1) - 1
    if remaining <= 0:
        _redis_pending.pop(tail_key, None)
        _redis_drop_warned.discard(tail_key)
    else:
        _redis_pending[tail_key] = remaining


async def drain_redis_mutations(timeout: float = _DRAIN_TIMEOUT_S) -> None:
    """Await pending Redis background mutations, up to *timeout* seconds.

    Call before closing the Redis pool at shutdown so queued writes and
    deletes land instead of dying with the loop. Tasks that outlive the
    window keep running in the background; nothing raises here.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    pending = [
        t for t in list(_redis_bg_tasks) if not t.done() and t.get_loop() is loop
    ]
    if not pending:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True), timeout=timeout
        )
    except TimeoutError:
        log.debug(
            "Redis drain timed out with %d mutations still pending.", len(pending)
        )


def _clear_redis_tail(
    tail_key: tuple[str, asyncio.AbstractEventLoop],
    task: asyncio.Task[None],
) -> None:
    """Release a namespace tail when no newer mutation follows it."""
    if _redis_tails.get(tail_key) is task:
        _redis_tails.pop(tail_key, None)


def _redis_client() -> Any:
    """Return the active Redis client instance, or None when Redis is not configured."""
    return _redis_mod.client()


def _log_redis_task_error(task: asyncio.Task[None]) -> None:
    """Done-callback: log Redis background task errors without raising."""
    if not task.cancelled() and task.exception() is not None:
        log.debug("Redis background task failed: %s", task.exception())
