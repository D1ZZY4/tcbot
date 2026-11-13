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
from tcbot.database.cache import redis_io
from tcbot.database.cache.codec import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)
from tcbot.database.cache.memory import CACHE_MISS, TTLCache
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

log = get_logger(__name__)

# * Revocation prefixes: role, connection, group-list, and owner state must
# * never be dropped by the mutation-queue bound, or other processes keep
# * serving revoked privileges until the Redis TTL (90-360 s). Display-name
# * hints (umention) may drop; the next update refreshes them.
_REVOCATION_PREFIXES: frozenset[str] = frozenset({"role", "conn", "groups", "owner"})

# * Keys per Redis MGET in the batch read. The command grows with the
# * key count, so a large batch is split into bounded chunks.
_MGET_CHUNK_SIZE: int = 500


class _KeyState:
    """Single-flight lock plus the invalidation counter of one key.

    The counter advances on every write and every invalidation, so a
    fetch that started before the change can tell that its result is
    stale and must not overwrite the newer value. The lock stays in
    place for the whole fetch, so concurrent readers of one key still
    share a single source read.
    """

    __slots__ = ("generation", "lock", "waiters")

    def __init__(self) -> None:
        self.generation: int = 0
        self.lock: asyncio.Lock = asyncio.Lock()
        self.waiters: int = 0


class TwoLevelCache[T]:
    """Two-level cache: in-memory L1 (fast) + Redis L2 (distributed, optional).

    When Redis is unavailable the cache degrades to pure in-memory behaviour
    identical to ``TTLCache``.  No configuration changes are required at call
    sites.
    """

    __slots__ = ("_is_revocation", "_mem", "_redis_prefix", "_redis_ttl", "_states")

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
        # * The revocation decision is taken once, so a caller that
        # * renames the prefix cannot turn a revocation write into a
        # * droppable one.
        self._is_revocation: bool = redis_prefix in _REVOCATION_PREFIXES
        # * Per-key state serialises concurrent fetches for one key across
        # * L1 + L2 + DB and carries the invalidation counter. The entry is
        # * dropped when the last waiter leaves, so the map stays bounded.
        self._states: dict[Any, _KeyState] = {}

    # ── Sync operations (in-memory layer only) ── #

    def get(self, key: Any) -> T | object:
        """Return the in-memory cached value, or CACHE_MISS."""
        return self._mem.get(key)

    def put(self, key: Any, val: T) -> None:
        """Store in memory and enqueue an ordered Redis write."""
        self._mem.put(key, val)
        # * Advance the key's generation so a fetch that started before
        # * this write cannot overwrite the newer value with an older one.
        self._advance(key)
        self._redis_put_background(key, val)

    def invalidate(self, key: Any) -> None:
        """Remove from memory and enqueue an ordered Redis delete.

        Deletes for revocation prefixes (role, connection, group list,
        owner) are never droppable: a dropped role revocation would leave
        other processes serving the revoked privilege until the key TTL.
        """
        self._mem.invalidate(key)
        # * Advance the key's generation so an in-flight fetch discards its
        # * stale result instead of resurrecting the revoked value.
        self._advance(key)
        self._redis_del_background(key, droppable=not self._is_revocation)

    def clear(self) -> None:
        """Clear the in-memory layer (does not flush Redis keys)."""
        self._mem.clear()
        # * Advance every known generation so an in-flight fetch discards
        # * its pre-clear result instead of writing it back into L1.
        for state in self._states.values():
            state.generation += 1

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
        # * Advance every known generation so an in-flight fetch discards
        # * its pre-sweep result.
        for state in self._states.values():
            state.generation += 1
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
                        timeout=redis_io._REDIS_WRITE_TIMEOUT_S,
                    )
                    if keys:
                        await asyncio.wait_for(
                            live.unlink(*keys),
                            timeout=redis_io._REDIS_WRITE_TIMEOUT_S,
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

        task = redis_io.enqueue_redis_mutation(
            self._redis_prefix, _clear_redis, droppable=False
        )
        if task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=redis_io._CLEAR_ALL_TIMEOUT_S,
                )
            except TimeoutError:
                log.warning(
                    "Redis clear_all for prefix %s still running after %ds; "
                    "continuing with L1 cleared.",
                    self._redis_prefix,
                    redis_io._CLEAR_ALL_TIMEOUT_S,
                )

    # ── Async hot-path ── #

    async def peek(self, key: Any) -> T | object:
        """Return the cached value from L1 or L2, or ``CACHE_MISS``.

        Reads the cached value without falling back to a database fetch.
        A caller that only wants to compare against the cached value (a
        change detector) must not pay for a round trip it does not need,
        but it must still see the L2 entry: the in-memory layer is bounded
        and thrashes once the federation is larger than its capacity.

        The value may be stale: an invalidation queues the Redis delete,
        so a read that races it can still observe the old entry. Use this
        for display hints, not for authoritative state; the revocation
        prefixes read through :meth:`get_or_fetch`, which discards a value
        whose key was invalidated while the read was in flight.

        A Redis outage is a miss, not an error: the caller decides what an
        unknown value means.
        """
        val = self._mem.get(key)
        if val is not CACHE_MISS:
            return val
        rc = await self._client()
        if rc is None:
            return CACHE_MISS
        rkey = self._rkey(key)
        try:
            raw = await asyncio.wait_for(
                rc.get(rkey),
                timeout=redis_io._REDIS_GET_TIMEOUT_S,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis peek failed for %s: %s", rkey, exc)
            return CACHE_MISS
        _redis_mod.mark_op(ok=True)
        if raw is None:
            return CACHE_MISS
        try:
            loaded: T = _decode_redis_value(raw)
        except Exception as exc:
            log.debug("Redis payload decode failed for %s: %s", rkey, exc)
            return CACHE_MISS
        self._mem.put(key, loaded)
        return loaded

    async def peek_many(self, keys: Sequence[Any]) -> dict[Any, T]:
        """Return the cached values for *keys* from L1 or L2.

        One L1 pass plus at most one Redis round trip for the keys L1
        missed. A per-key :meth:`peek` would cost one round trip per
        key, which is exactly what the batch readers exist to avoid.

        The values may be stale for the same reason :meth:`peek` values
        may be stale: an invalidation queues the Redis delete, so a read
        that races it can still observe the old entry.

        A Redis outage is a miss, not an error: the keys it could not
        answer are simply absent from the result.
        """
        found: dict[Any, T] = {}
        missing: list[Any] = []
        for key in keys:
            val = self._mem.get(key)
            if val is CACHE_MISS:
                missing.append(key)
            else:
                found[key] = cast("T", val)
        if not missing:
            return found
        rc = await self._client()
        if rc is None:
            return found
        # * The keys are read in bounded chunks, so a large batch cannot
        # * build one oversized command.
        for start in range(0, len(missing), _MGET_CHUNK_SIZE):
            chunk = missing[start : start + _MGET_CHUNK_SIZE]
            try:
                raws = await asyncio.wait_for(
                    rc.mget(*[self._rkey(key) for key in chunk]),
                    timeout=redis_io._REDIS_GET_TIMEOUT_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _redis_mod.mark_op(ok=False)
                log.debug(
                    "Redis mget failed for prefix %s: %s",
                    self._redis_prefix,
                    exc,
                )
                return found
            _redis_mod.mark_op(ok=True)
            for key, raw in zip(chunk, raws, strict=False):
                if raw is None:
                    continue
                try:
                    loaded: T = _decode_redis_value(raw)
                except Exception as exc:
                    log.debug(
                        "Redis payload decode failed for %s: %s",
                        self._rkey(key),
                        exc,
                    )
                    continue
                self._mem.put(key, loaded)
                found[key] = loaded
        return found

    async def get_or_fetch(
        self,
        key: Any,
        fetch: Callable[[], Awaitable[T]],
    ) -> T:
        """L1 -> L2 -> DB fetch with population of both layers on a miss.

        Layers checked in order:
        1. In-memory (sub-microsecond, no I/O).
        2. Redis (single round-trip, returns cached value from another process
           or previous bot run).
        3. ``fetch()`` coroutine (DB query); result is written to both layers.

        A per-key lock serialises concurrent misses for the same key so
        that only one ``fetch()`` runs; the winner populates the cache
        and all waiters read the same result. Different keys remain fully
        parallel. A value whose key was invalidated while the read was in
        flight is discarded instead of published.
        """
        val = self._mem.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)

        state = self._state(key)
        state.waiters += 1
        try:
            async with state.lock:
                # * Re-check L1 inside the lock to catch a winner that just populated it.
                val = self._mem.get(key)
                if val is not CACHE_MISS:
                    return cast("T", val)
                generation = state.generation

                # L2: Redis (bounded: a stalled Redis must not hold the hot path)
                rc = await self._client()
                if rc is not None:
                    rkey = self._rkey(key)
                    try:
                        raw = await asyncio.wait_for(
                            rc.get(rkey),
                            timeout=redis_io._REDIS_GET_TIMEOUT_S,
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
                                if state.generation != generation:
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
                if state.generation != generation:
                    # * The key was invalidated or overwritten while the
                    # * fetch was in flight. The fetched value predates the
                    # * change, so caching it would resurrect a revoked
                    # * privilege for the whole L1/L2 TTL. The caller still
                    # * receives the value it asked for.
                    log.debug("Discarding stale fetch for invalidated key %s", key)
                    return cast("T", val)
                self._publish(key, val)
                return cast("T", val)
        finally:
            self._release(key, state)

    async def refresh(self, key: Any, fetch: Callable[[], Awaitable[T]]) -> T:
        """Re-read *key* from the source and publish the result.

        A fresh read that lands after a write must not undo it: the
        value the read carries predates the change, so publishing it
        would resurrect a revoked role for the whole TTL. The generation
        counter detects that race, and the stale value is returned to the
        caller without being cached.
        """
        state = self._state(key)
        state.waiters += 1
        try:
            async with state.lock:
                generation = state.generation
                val = await fetch()
                if state.generation != generation:
                    log.debug("Discarding stale refresh for invalidated key %s", key)
                    return val
                self._publish(key, val)
                return val
        finally:
            self._release(key, state)

    # ── Internal helpers ── #

    def _state(self, key: Any) -> _KeyState:
        """Return the single-flight state of *key*, creating it on first use."""
        state = self._states.get(key)
        if state is None:
            state = _KeyState()
            self._states[key] = state
        return state

    def _release(self, key: Any, state: _KeyState) -> None:
        """Drop the state of *key* once its last waiter left."""
        state.waiters -= 1
        if state.waiters == 0 and self._states.get(key) is state:
            del self._states[key]

    def _advance(self, key: Any) -> None:
        """Advance the generation of *key* so in-flight fetches discard."""
        state = self._states.get(key)
        if state is not None:
            state.generation += 1

    def _publish(self, key: Any, val: T) -> None:
        """Store *val* in the memory layer and enqueue the ordered Redis write."""
        self._mem.put(key, val)
        self._enqueue_write(key, val)

    def _enqueue_write(self, key: Any, val: T) -> None:
        """Enqueue the ordered Redis write for *key* without blocking.

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
        redis_io.enqueue_redis_mutation(
            self._redis_prefix,
            lambda: self._redis_set(rkey, payload),
            droppable=not self._is_revocation,
        )

    async def _client(self) -> Any:
        """Return the Redis client, reconnecting after a failed startup.

        The client is resolved through the redis_io module so a patched
        client keeps working; only a missing client triggers the
        reconnect, which the client module rate-limits.
        """
        rc = redis_io.redis_client()
        if rc is None:
            rc = await redis_io.acquire_redis_client()
        return rc

    def _rkey(self, key: Any) -> str:
        return f"tcbot:{self._redis_prefix}:v2:{key}"

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller."""
        self._enqueue_write(key, val)

    def _redis_del_background(self, key: Any, *, droppable: bool = True) -> None:
        """Fire-and-forget Redis key deletion without blocking the caller."""
        if not cfg.redis_url:
            return
        rkey = self._rkey(key)
        redis_io.enqueue_redis_mutation(
            self._redis_prefix,
            lambda: self._redis_delete(rkey),
            droppable=droppable,
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
                timeout=redis_io._REDIS_WRITE_TIMEOUT_S,
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
                timeout=redis_io._REDIS_WRITE_TIMEOUT_S,
            )
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis delete failed for %s: %s", rkey, exc)
        else:
            _redis_mod.mark_op(ok=True)
