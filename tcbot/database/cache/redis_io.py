# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis boundary of the two-level cache: client access, timeouts, FIFO queue."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import tcbot.database.redis_client as _redis_mod
from tcbot.utils import metrics
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
# * a memory leak that outlives the outage. At this ceiling a droppable op
# * is dropped, and a revocation first evicts a droppable op that has not
# * started. When none can be evicted, the revocation is dropped here too:
# * the revoked state then survives until the key TTL, which is recoverable,
# * while exhausting process memory is not.
_REDIS_HARD_MAX_PENDING: int = 1000
# * Final backstop for a queue already above the hard ceiling. Normal
# * operation bounds the queue at the hard ceiling first, so this value is
# * only reached when a backlog was created under a lower limit.
_REDIS_ABSOLUTE_MAX_PENDING: int = 2000
_redis_pending: dict[tuple[str, asyncio.AbstractEventLoop], int] = {}
_redis_drop_warned: set[tuple[str, asyncio.AbstractEventLoop]] = set()
# * Droppable mutations that have not started yet, oldest first. A critical
# * op evicts one of these (a display hint can wait for its next refresh)
# * instead of being dropped itself.
_redis_cancellable: dict[
    tuple[str, asyncio.AbstractEventLoop], list[asyncio.Task[None]]
] = {}
# * Tasks currently inside their Redis call. Cancelling one would leave its
# * reply unread on a pooled connection, so they are never evicted.
_redis_running: set[asyncio.Task[None]] = set()
# * Grace window for draining background mutations before the pool closes.
_DRAIN_TIMEOUT_S: float = 5.0
# * Ceiling for one clear_all wait; the sweep keeps running past it so a
# * dead-Redis backlog delays the caller briefly instead of stalling it.
_CLEAR_ALL_TIMEOUT_S: float = 10.0
# * Per-operation deadlines belong to the client's socket timeout, not to a
# * ``wait_for`` wrapper: cancelling a Redis command leaves its reply unread
# * on the pooled connection, and the next command would read that stale
# * reply. ``redis_client`` owns the socket timeout and disconnects a
# * connection that times out before it returns to the pool.


# ─────────────────────────── Client access ─────────────────────────── #


def usable_redis_client() -> Any:
    """Return the Redis client, or None when it cannot serve this loop.

    A client whose sockets belong to another event loop would wait for
    an answer that can never arrive, so it is reported as absent and the
    cache falls back to its in-memory layer.
    """
    client = _redis_mod.client()
    if client is None or not _redis_mod.client_is_usable():
        metrics.set_redis_available(available=False)
        return None
    metrics.set_redis_available(available=True)
    return client


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
        metrics.set_queue_depth(tail_key[0], 0)
    else:
        _redis_pending[tail_key] = remaining
        metrics.set_queue_depth(tail_key[0], remaining)


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


def _forget_cancellable(
    tail_key: tuple[str, asyncio.AbstractEventLoop], task: asyncio.Task[None]
) -> None:
    """Done-callback: drop a finished task from the evictable list."""
    queued = _redis_cancellable.get(tail_key)
    if queued is None:
        return
    try:
        queued.remove(task)
    except ValueError:
        return
    if not queued:
        _redis_cancellable.pop(tail_key, None)


def _evict_droppable(tail_key: tuple[str, asyncio.AbstractEventLoop]) -> bool:
    """Cancel the oldest droppable mutation that has not started.

    The successor of the cancelled task awaits it through a shielded
    handle and continues on cancellation, so removing one link does not
    break the FIFO tail. A task already inside its Redis call is skipped:
    cancelling it would leave a reply unread on the pooled connection.
    """
    queued = _redis_cancellable.get(tail_key)
    if not queued:
        return False
    while queued:
        task = queued.pop(0)
        if task.done() or task in _redis_running:
            continue
        task.cancel()
        return True
    return False


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

    At the hard ceiling a critical op evicts the oldest droppable op that
    has not started. If none can be evicted, the revocation is dropped to
    keep the queue bounded; the absolute ceiling is a final backstop for a
    queue already above the hard limit.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("Redis mutation skipped for prefix %s: no running loop.", prefix)
        return None

    tail_key = (prefix, loop)
    depth = _redis_pending.get(tail_key, 0)
    if depth >= _REDIS_HARD_MAX_PENDING:
        if (
            not droppable
            and depth < _REDIS_ABSOLUTE_MAX_PENDING
            and _evict_droppable(tail_key)
        ):
            # * The evicted task releases its slot on the next loop tick;
            # * this critical op may sit one past the soft ceiling until
            # * then, which is bounded.
            log.warning(
                "Redis mutation queue full for prefix %s (%d pending); "
                "evicted a droppable op to queue a revocation.",
                prefix,
                depth,
            )
            metrics.record_eviction(prefix)
        else:
            # * Absolute ceiling: a dead Redis would otherwise grow the
            # * queue without bound. Dropping a revocation leaves the
            # * revoked state visible until the key TTL, which is
            # * recoverable; exhausting the process memory is not.
            log.error(
                "Redis mutation queue critically full for prefix %s (%d pending); "
                "dropping op to keep memory bounded.",
                prefix,
                depth,
            )
            metrics.record_drop(prefix)
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
        metrics.record_drop(prefix)
        return None
    _redis_pending[tail_key] = depth + 1
    metrics.set_queue_depth(prefix, depth + 1)
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
        task = asyncio.current_task()
        if task is not None:
            _redis_running.add(task)
        try:
            await operation()
        finally:
            if task is not None:
                _redis_running.discard(task)

    task = loop.create_task(_run(), name=f"tcbot.redis.{prefix}")
    _redis_tails[tail_key] = task
    _redis_bg_tasks.add(task)
    if droppable:
        _redis_cancellable.setdefault(tail_key, []).append(task)
        task.add_done_callback(
            lambda completed: _forget_cancellable(tail_key, completed)
        )
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
    # * asyncio.wait does not cancel the tasks it stops waiting for, unlike
    # * wait_for(gather(...)), which would abort the very mutations the drain
    # * promises to leave running.
    _done, still_pending = await asyncio.wait(pending, timeout=timeout)
    if still_pending:
        log.debug(
            "Redis drain timed out with %d mutations still pending.",
            len(still_pending),
        )
