# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Two-level TTL cache: in-process L1 plus optional Redis L2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import msgspec

import tcbot.database.redis_client as _redis_mod
from tcbot.database import cache as _cache_pkg
from tcbot.database.cache.codec import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)
from tcbot.database.cache.memory import CACHE_MISS, TTLCache
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

# * Client and timeouts resolve via the package namespace so patching
# * tcbot.database.cache keeps working as with the old single module.


class TwoLevelCache[T]:
    """Two-level cache: in-memory L1 (fast) + Redis L2 (distributed, optional).

    When Redis is unavailable the cache degrades to pure in-memory behaviour
    identical to ``TTLCache``.  No configuration changes are required at call
    sites.
    """

    __slots__ = ("_locks", "_mem", "_redis_prefix", "_redis_ttl")

    def __init__(
        self,
        memory_ttl: float,
        redis_ttl: float,
        redis_prefix: str,
        maxsize: int = 512,
    ) -> None:
        """Initialise with separate TTLs for each layer, a Redis key prefix, and maxsize."""
        self._mem: TTLCache[T] = TTLCache(ttl=memory_ttl, maxsize=maxsize)
        self._redis_ttl: int = max(1, int(redis_ttl))
        self._redis_prefix: str = redis_prefix
        # * Per-key lock serialises concurrent fetches for one key across
        # * L1 + L2 + DB. Dropped per fetch (and in invalidate) to bound
        # * growth; clear() leaves in-flight locks alone.
        self._locks: dict[Any, asyncio.Lock] = {}

    # ── Sync operations (in-memory layer only) ── #

    def get(self, key: Any) -> T | object:
        """Return the in-memory cached value, or CACHE_MISS."""
        return self._mem.get(key)

    def put(self, key: Any, val: T) -> None:
        """Store in memory and enqueue an ordered Redis write."""
        self._mem.put(key, val)
        self._redis_put_background(key, val)

    def invalidate(self, key: Any) -> None:
        """Remove from memory and enqueue an ordered Redis delete."""
        self._mem.invalidate(key)
        # * Drop the per-key lock so high-cardinality callers do not
        # * accumulate a stale lock for every key ever fetched.
        self._locks.pop(key, None)
        self._redis_del_background(key)

    def clear(self) -> None:
        """Clear the in-memory layer (does not flush Redis keys)."""
        self._mem.clear()

    async def clear_all(self) -> None:
        """Clear the in-memory layer AND delete all matching keys from Redis.

        Use this when you need a full two-layer invalidation and the set of
        affected keys is not known in advance (e.g. after an ownership transfer
        where the previous owner's ID is unavailable).  Unlike ``clear()``,
        this method is async and removes Redis keys via SCAN + UNLINK in
        batches of 100, avoiding the O(N) blocking behaviour of ``KEYS``.

        Unlike ``invalidate(key)``, which removes one known key from both layers,
        this sweeps every key matching ``tcbot:<prefix>:v2:*``.  Do not call it in
        hot paths; it is designed for rare, high-impact invalidations only.
        The Redis sweep is never dropped by the mutation-queue bound, and the
        wait for it is bounded so a dead-Redis backlog cannot stall the caller
        (the sweep keeps running in the background and L1 is already clear).
        """
        self._mem.clear()
        pattern = f"tcbot:{self._redis_prefix}:v2:*"

        async def _clear_redis() -> None:
            live = _cache_pkg._redis_client()
            if live is None:
                return
            cursor: int = 0
            try:
                while True:
                    cursor, keys = await live.scan(cursor, match=pattern, count=100)
                    if keys:
                        await live.unlink(*keys)
                    if cursor == 0:
                        break
            except Exception as exc:
                log.debug(
                    "Redis clear_all failed for prefix %s: %s",
                    self._redis_prefix,
                    exc,
                )

        task = self._enqueue_redis_mutation(_clear_redis, droppable=False)
        if task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=_cache_pkg._CLEAR_ALL_TIMEOUT_S,
                )
            except TimeoutError:
                log.warning(
                    "Redis clear_all for prefix %s still running after %ds; "
                    "continuing with L1 cleared.",
                    self._redis_prefix,
                    _cache_pkg._CLEAR_ALL_TIMEOUT_S,
                )

    # ── Async hot-path ── #

    async def get_or_fetch(
        self,
        key: Any,
        fetch: Callable[[], Awaitable[T]],
    ) -> T:
        """L1 → L2 → DB fetch with population of both layers on a miss.

        Layers checked in order:
        1. In-memory (sub-microsecond, no I/O).
        2. Redis (single round-trip, returns cached value from another process
           or previous bot run).
        3. ``fetch()`` coroutine (DB query); result is written to both layers.

        A per-key ``asyncio.Lock`` serialises concurrent misses for the same
        key so that only one ``fetch()`` runs; the winner populates the cache
        and all waiters read the same result. Different keys remain fully
        parallel. Mirrors ``TTLCache.get_or_fetch`` semantics.
        """
        val = self._mem.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)

        # * Re-check L1 inside the lock to catch a winner that just populated it.
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                val = self._mem.get(key)
                if val is not CACHE_MISS:
                    return cast("T", val)

                # L2: Redis (bounded: a stalled Redis must not hold the hot path)
                rc = _cache_pkg._redis_client()
                if rc is not None:
                    rkey = self._rkey(key)
                    try:
                        raw = await asyncio.wait_for(
                            rc.get(rkey),
                            timeout=_cache_pkg._REDIS_GET_TIMEOUT_S,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        _redis_mod.mark_op(ok=False)
                        log.debug("Redis get failed for %s: %s", rkey, exc)
                    else:
                        # * Any response proves Redis is alive; only a
                        # * transport failure marks it down.
                        _redis_mod.mark_op(ok=True)
                        if raw is not None:
                            try:
                                loaded: T = _decode_redis_value(raw)
                            except Exception as exc:
                                # * Corrupt payload is a miss, not an outage.
                                log.debug(
                                    "Redis payload decode failed for %s: %s",
                                    rkey,
                                    exc,
                                )
                            else:
                                self._mem.put(key, loaded)
                                return loaded

                # * L2 write is fire-and-forget and ordered FIFO against
                # * later invalidates; L1 already serves this value.
                # * Enqueued unconditionally so a reconnect before the
                # * write still lands the value.
                val = await fetch()
                self._mem.put(key, val)
                rkey = self._rkey(key)
                try:
                    payload = msgspec.json.encode(
                        _tag_scalars(val), enc_hook=_msgspec_enc_hook
                    ).decode("utf-8")
                except Exception as exc:
                    # * L1 already serves this value: never fail the hot path here.
                    log.debug("Redis payload encode failed for %s: %s", rkey, exc)
                else:
                    self._enqueue_redis_mutation(lambda: self._redis_set(rkey, payload))

                return cast("T", val)
        finally:
            # * Waiters hold their own reference; the value is already in L1.
            self._locks.pop(key, None)

    # ── Internal helpers ── #

    def _rkey(self, key: Any) -> str:
        return f"tcbot:{self._redis_prefix}:v2:{key}"

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller."""
        rc = _cache_pkg._redis_client()
        if rc is None:
            return
        rkey = self._rkey(key)
        # * L1 already serves this value: skip the L2 write, never raise.
        try:
            payload = msgspec.json.encode(
                _tag_scalars(val), enc_hook=_msgspec_enc_hook
            ).decode("utf-8")
        except Exception as exc:
            log.debug("Redis payload encode failed for %s: %s", rkey, exc)
            return
        self._enqueue_redis_mutation(lambda: self._redis_set(rkey, payload))

    def _redis_del_background(self, key: Any) -> None:
        """Fire-and-forget Redis key deletion without blocking the caller."""
        rc = _cache_pkg._redis_client()
        if rc is None:
            return
        rkey = self._rkey(key)
        self._enqueue_redis_mutation(lambda: self._redis_delete(rkey))

    async def _redis_set(self, rkey: str, payload: str) -> None:
        """Write one Redis value and keep failures observable but non-fatal.

        The client resolves at run time, not enqueue time: a reconnect
        between queueing and execution must not write through a dead pool.
        The per-op wait_for abandons a stalled write (the socket timeout
        bounds the underlying op); abandonment only delays an L2 hint.
        """
        rc = _cache_pkg._redis_client()
        if rc is None:
            return
        try:
            await asyncio.wait_for(
                rc.set(rkey, payload, ex=self._redis_ttl),
                timeout=_cache_pkg._REDIS_WRITE_TIMEOUT_S,
            )
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis set failed for %s: %s", rkey, exc)
        else:
            _redis_mod.mark_op(ok=True)

    async def _redis_delete(self, rkey: str) -> None:
        """Delete one Redis value and keep failures observable but non-fatal."""
        rc = _cache_pkg._redis_client()
        if rc is None:
            return
        try:
            await asyncio.wait_for(
                rc.delete(rkey),
                timeout=_cache_pkg._REDIS_WRITE_TIMEOUT_S,
            )
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis delete failed for %s: %s", rkey, exc)
        else:
            _redis_mod.mark_op(ok=True)

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
        until the key TTL.
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
                try:
                    await previous
                except asyncio.CancelledError:
                    # ! CRITICAL: the chain is being torn down; running the
                    # ! queued mutation anyway would delay shutdown and risk
                    # ! writing stale state after a newer invalidation.
                    raise
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
