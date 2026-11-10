# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Two-level TTL cache: in-process L1 plus optional Redis L2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import msgspec

import tcbot.database.redis_client as _redis_mod
from tcbot import cfg
from tcbot.database import cache as _cache_pkg
from tcbot.database.cache.codec import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)
from tcbot.database.cache.memory import CACHE_MISS, TTLCache
from tcbot.database.cache.twolevel.queue import _QueueMixin
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = get_logger(__name__)

# * Revocation prefixes: role, connection, group-list, and owner state must
# * never be dropped by the mutation-queue bound, or other processes keep
# * serving revoked privileges until the Redis TTL (90-360 s). Display-name
# * hints (umention) may drop; the next update refreshes them.
_REVOCATION_PREFIXES: frozenset[str] = frozenset({"role", "conn", "groups", "owner"})

# * Client and timeouts resolve via the package namespace so patching
# * tcbot.database.cache keeps working as with the old single module.


class TwoLevelCache[T](_QueueMixin):
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
        # * Drop the per-key lock so a fetch that started before this write
        # * cannot overwrite the newer value with an older one.
        self._locks.pop(key, None)
        self._redis_put_background(key, val)

    def invalidate(self, key: Any) -> None:
        """Remove from memory and enqueue an ordered Redis delete.

        Deletes for revocation prefixes (role, connection, group list,
        owner) are never droppable: a dropped role revocation would leave
        other processes serving the revoked privilege until the key TTL.
        """
        self._mem.invalidate(key)
        # * Drop the per-key lock so high-cardinality callers do not
        # * accumulate a stale lock for every key ever fetched. The drop
        # * also signals the in-flight fetch for this key that its result
        # * predates the invalidation (see get_or_fetch).
        self._locks.pop(key, None)
        self._redis_del_background(
            key, droppable=self._redis_prefix not in _REVOCATION_PREFIXES
        )

    def clear(self) -> None:
        """Clear the in-memory layer (does not flush Redis keys)."""
        self._mem.clear()
        # * Drop the per-key locks so a fetch that started before the clear
        # * cannot write its pre-clear value back into L1.
        self._locks.clear()

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
        # * Drop the per-key locks so a fetch that started before the sweep
        # * cannot write its pre-clear value back into L1.
        self._locks.clear()
        pattern = f"tcbot:{self._redis_prefix}:v2:*"

        async def _clear_redis() -> None:
            live = await self._client()
            if live is None:
                return
            cursor: int = 0
            try:
                while True:
                    cursor, keys = await asyncio.wait_for(
                        live.scan(cursor, match=pattern, count=100),
                        timeout=_cache_pkg._REDIS_WRITE_TIMEOUT_S,
                    )
                    if keys:
                        await asyncio.wait_for(
                            live.unlink(*keys),
                            timeout=_cache_pkg._REDIS_WRITE_TIMEOUT_S,
                        )
                    if cursor == 0:
                        break
            except asyncio.CancelledError:
                raise
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
                rc = await self._client()
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
                                if self._locks.get(key) is not lock:
                                    # * The key was invalidated while the
                                    # * Redis read was in flight: the payload
                                    # * predates the change and must not be
                                    # * cached, or the revoked value comes
                                    # * back for a whole TTL.
                                    log.debug(
                                        "Discarding stale Redis hit for "
                                        "invalidated key %s",
                                        key,
                                    )
                                    return loaded
                                self._mem.put(key, loaded)
                                return loaded

                # * L2 write is fire-and-forget and ordered FIFO against
                # * later invalidates; L1 already serves this value.
                # * Enqueued unconditionally so a reconnect before the
                # * write still lands the value.
                val = await fetch()
                if self._locks.get(key) is not lock:
                    # * The key was invalidated or overwritten while the
                    # * fetch was in flight. The fetched value predates the
                    # * change, so caching it would resurrect a revoked
                    # * privilege for the whole L1/L2 TTL. The caller still
                    # * receives the value it asked for.
                    log.debug("Discarding stale fetch for invalidated key %s", key)
                    return cast("T", val)
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
                    if cfg.redis_url:
                        self._enqueue_redis_mutation(
                            lambda: self._redis_set(rkey, payload),
                            droppable=self._redis_prefix not in _REVOCATION_PREFIXES,
                        )

                return cast("T", val)
        finally:
            # * Waiters hold their own reference; the value is already in L1.
            # * Remove only our own lock: invalidate() or a later fetch may
            # * have replaced it, and popping that replacement would break
            # * mutual exclusion for the waiters still holding the new lock.
            if self._locks.get(key) is lock:
                self._locks.pop(key, None)

    # ── Internal helpers ── #

    async def _client(self) -> Any:
        """Return the Redis client, reconnecting after a failed startup.

        The client is resolved through the package namespace first so a
        patched client keeps working; only a missing client triggers the
        reconnect, which the client module rate-limits.
        """
        rc = _cache_pkg._redis_client()
        if rc is None:
            rc = await _cache_pkg.acquire_redis_client()
        return rc

    def _rkey(self, key: Any) -> str:
        return f"tcbot:{self._redis_prefix}:v2:{key}"

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller.

        Writes for revocation prefixes are never droppable: a dropped
        connection-flag write (for example a disconnect) would leave other
        processes serving the pre-write state until the key TTL.
        """
        if not cfg.redis_url:
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
        self._enqueue_redis_mutation(
            lambda: self._redis_set(rkey, payload),
            droppable=self._redis_prefix not in _REVOCATION_PREFIXES,
        )

    def _redis_del_background(self, key: Any, *, droppable: bool = True) -> None:
        """Fire-and-forget Redis key deletion without blocking the caller."""
        if not cfg.redis_url:
            return
        rkey = self._rkey(key)
        self._enqueue_redis_mutation(
            lambda: self._redis_delete(rkey), droppable=droppable
        )

    async def _redis_set(self, rkey: str, payload: str) -> None:
        """Write one Redis value and keep failures observable but non-fatal.

        The client resolves at run time, not enqueue time: a reconnect
        between queueing and execution must not write through a dead pool.
        The per-op wait_for abandons a stalled write (the socket timeout
        bounds the underlying op); abandonment only delays an L2 hint.
        """
        rc = await self._client()
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
        rc = await self._client()
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
