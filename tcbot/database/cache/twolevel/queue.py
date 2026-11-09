# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""FIFO Redis mutation queue for TwoLevelCache."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.database.cache.mutations import (
    _REDIS_MAX_PENDING,
    _clear_redis_tail,
    _log_redis_task_error,
    _redis_bg_tasks,
    _redis_drop_warned,
    _redis_pending,
    _redis_tails,
    _release_redis_slot,
)
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = get_logger(__name__)


class _QueueMixin:
    """FIFO enqueue mixed into TwoLevelCache."""

    _redis_prefix: str

    def _enqueue_redis_mutation(
        self, operation: Callable[[], Awaitable[None]], *, droppable: bool = True
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
            log.debug(
                "Redis mutation skipped for prefix %s: no running loop.",
                self._redis_prefix,
            )
            return None

        tail_key = (self._redis_prefix, loop)
        depth = _redis_pending.get(tail_key, 0)
        if droppable and depth >= _REDIS_MAX_PENDING:
            if tail_key not in _redis_drop_warned:
                _redis_drop_warned.add(tail_key)
                log.warning(
                    "Redis mutation queue full for prefix %s (%d pending); "
                    "dropping newest op.",
                    self._redis_prefix,
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
                        self._redis_prefix,
                    )
                except BaseException as exc:
                    log.debug(
                        "Previous Redis mutation failed for prefix %s: %s",
                        self._redis_prefix,
                        exc,
                    )
            await operation()

        task = loop.create_task(_run(), name=f"tcbot.redis.{self._redis_prefix}")
        _redis_tails[tail_key] = task
        _redis_bg_tasks.add(task)
        task.add_done_callback(_redis_bg_tasks.discard)
        task.add_done_callback(_log_redis_task_error)
        task.add_done_callback(lambda completed: _clear_redis_tail(tail_key, completed))
        task.add_done_callback(lambda _: _release_redis_slot(tail_key))
        return task
