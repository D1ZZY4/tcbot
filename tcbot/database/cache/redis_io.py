# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis boundary of the two-level cache: client access, timeouts, FIFO queue."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import tcbot.database.redis_client as _redis_mod
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = get_logger(__name__)

# * Strong refs to in-flight tasks; prevents GC before completion.
_redis_bg_tasks: set[asyncio.Task[None]] = set()
# * FIFO order per (prefix, loop); asyncio tasks cannot await across loops.
_redis_tails: dict[tuple[str, asyncio.AbstractEventLoop], asyncio.Task[None]] = {}
# * Past this queued depth per (prefix, loop) droppable ops drop with a
# * warning. L2 is a TTL hint layer, so a drop only extends staleness to
# * the key TTL while an unbounded queue would stall revocation paths.
_REDIS_MAX_PENDING: int = 200
# * Hard ceiling for the queue depth, droppable ops included. A dead Redis
# * would otherwise grow the queue without bound, and an unbounded queue is
# * a memory leak that outlives the outage. Past this ceiling even a
# * revocation op is dropped, with an error-level warning: the revoked
# * state then survives until the key TTL instead of exhausting the
# * process memory.
_REDIS_HARD_MAX_PENDING: int = 1000
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


# ─────────────────────────── Client access ─────────────────────────── #


def redis_client() -> Any:
    """Return the active Redis client instance, or None when Redis is not configured."""
    return _redis_mod.client()


async def acquire_redis_client() -> Any:
    """Return the Redis client, reconnecting after a failed startup.

    The shared cache is optional, so a Redis that was down at boot must
    not disable it for the rest of the process lifetime. The reconnect is
    rate-limited by the client module; this helper only awaits it.
    """
    client = _redis_mod.client()
    if client is not None:
        return client
    return await _redis_mod.ensure_connected()


# ──────────────────────────── FIFO queue ───────────────────────────── #


def _release_redis_slot(tail_key: tuple[str, asyncio.AbstractEventLoop]) -> None:
    """Decrement the queued-mutation depth and re-arm the drop warning."""
    remaining = _redis_pending.get(tail_key, 1) - 1
    if remaining <= 0:
        _redis_pending.pop(tail_key, None)
        _redis_drop_warned.discard(tail_key)
    else:
        _redis_pending[tail_key] = remaining


def _clear_redis_tail(
    tail_key: tuple[str, asyncio.AbstractEventLoop],
    task: asyncio.Task[None],
) -> None:
    """Release a namespace tail when no newer mutation follows it."""
    if _redis_tails.get(tail_key) is task:
        _redis_tails.pop(tail_key, None)


def _log_redis_task_error(task: asyncio.Task[None]) -> None:
    """Done-callback: log Redis background task errors without raising."""
    if not task.cancelled() and task.exception() is not None:
        log.debug("Redis background task failed: %s", task.exception())


def enqueue_redis_mutation(
    prefix: str,
    operation: Callable[[], Awaitable[None]],
    *,
    droppable: bool = True,
) -> asyncio.Task[None] | None:
    """Run Redis mutations FIFO for this Redis prefix and event loop.

    ``put()``, ``invalidate()``, and ``clear_all()`` are called from
    different synchronous and asynchronous paths.  Chaining each operation
    to the previous task prevents a slower Redis write from completing
    after a newer delete or prefix-wide clear, including when separate
    cache objects share the same Redis namespace.

    The queue is bounded: past ``_REDIS_MAX_PENDING`` queued ops a
    droppable op drops with a warning instead of growing memory.
    ``clear_all()`` enqueues with ``droppable=False``: a prefix-wide
    revocation (e.g. after an ownership transfer) must never be
    dropped, or other processes keep serving revoked roles from L2
    until the key TTL. Single-key deletes and writes for revocation
    prefixes (``role``, ``conn``, ``groups``, ``owner``) take the same
    non-droppable path for the same reason; display-name hints
    (``umention``) remain droppable.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("Redis mutation skipped for prefix %s: no running loop.", prefix)
        return None

    tail_key = (prefix, loop)
    depth = _redis_pending.get(tail_key, 0)
    if depth >= _REDIS_HARD_MAX_PENDING:
        # * Hard ceiling: a dead Redis would otherwise grow the queue
        # * without bound. Dropping a revocation leaves the revoked
        # * state visible until the key TTL, which is recoverable;
        # * exhausting the process memory is not.
        log.error(
            "Redis mutation queue critically full for prefix %s (%d pending); "
            "dropping op to keep memory bounded.",
            prefix,
            depth,
        )
        return None
    if droppable and depth >= _REDIS_MAX_PENDING:
        if tail_key not in _redis_drop_warned:
            _redis_drop_warned.add(tail_key)
            log.warning(
                "Redis mutation queue full for prefix %s (%d pending); "
                "dropping newest op.",
                prefix,
                depth,
            )
        return None
    _redis_pending[tail_key] = depth + 1
    previous = _redis_tails.get(tail_key)

    async def _run() -> None:
        if previous is not None:
            # * Each mutation has its own fault domain: a cancelled
            # * predecessor must not drop the rest of the tail. Shielding
            # * surfaces the predecessor's CancelledError here without
            # * marking this task cancelled, so only a self-cancellation
            # * (cancelling() > 0) aborts the operation.
            try:
                await asyncio.shield(previous)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling() > 0:
                    raise
                log.debug(
                    "Previous Redis mutation cancelled for prefix %s; continuing",
                    prefix,
                )
            except BaseException as exc:
                log.debug(
                    "Previous Redis mutation failed for prefix %s: %s",
                    prefix,
                    exc,
                )
        await operation()

    task = loop.create_task(_run(), name=f"tcbot.redis.{prefix}")
    _redis_tails[tail_key] = task
    _redis_bg_tasks.add(task)
    task.add_done_callback(_redis_bg_tasks.discard)
    task.add_done_callback(_log_redis_task_error)
    task.add_done_callback(lambda completed: _clear_redis_tail(tail_key, completed))
    task.add_done_callback(lambda _: _release_redis_slot(tail_key))
    return task


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
