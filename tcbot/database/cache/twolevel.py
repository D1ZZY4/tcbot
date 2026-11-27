# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Two-level TTL cache: in-process L1 plus optional Redis L2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import msgspec

import tcbot.database.cache.redis_io as redis_io
import tcbot.database.redis_client as _redis_mod
from tcbot import cfg
from tcbot.database.cache.codec import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)
from tcbot.database.cache.memory import CACHE_MISS, TTLCache
from tcbot.utils import metrics
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

log = get_logger(__name__)

# * Revocation prefixes: role, connection, group-list, and owner state must
# * not be dropped by the mutation-queue bound, or other processes keep
# * serving revoked privileges until the Redis TTL (90-360 s). The queue
# * evicts a queued display hint before it drops one of these, and only an
# * absolute ceiling with no droppable op left can discard a revocation.
# * Display-name hints (umention) may drop; the next update refreshes them.
_REVOCATION_PREFIXES: frozenset[str] = frozenset({"role", "conn", "groups", "owner"})

# * A locale invalidation is also a revocation: a cached language that
# * survives another process serves the superseded language for up to
# * 600 s. The cache fill itself stays droppable because the next render
# * repopulates it, so only the delete is forced through the queue.
_LOCALE_PREFIXES: frozenset[str] = frozenset({"ulocale", "glocale", "clocale"})

# * Keys per Redis MGET in the batch read. The command grows with the
# * key count, so a large batch is split into bounded chunks.
_MGET_CHUNK_SIZE: int = 500

# * Short-lived marker written just before a revocation delete. It closes
# * the cross-process window where a reader could fetch the old L2 value
# * before the queued delete of another process lands.
_TOMBSTONE_TTL_S: int = 10


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

    __slots__ = (
        "_critical_delete",
        "_epoch",
        "_is_revocation",
        "_mem",
        "_pending_invalidations",
        "_pending_writes",
        "_redis_prefix",
        "_redis_ttl",
        "_revision",
        "_states",
    )

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
        # * droppable one. The delete class additionally covers the locale
        # * caches, whose fill is droppable but whose invalidation is not.
        self._is_revocation: bool = redis_prefix in _REVOCATION_PREFIXES
        self._critical_delete: bool = (
            self._is_revocation or redis_prefix in _LOCALE_PREFIXES
        )
        # * Per-key state serialises concurrent fetches for one key across
        # * L1 + L2 + DB and carries the invalidation counter. The entry is
        # * dropped when the last waiter leaves, so the map stays bounded.
        self._states: dict[Any, _KeyState] = {}
        # * Cache-wide invalidation counter. ``clear_all`` bumps it on both
        # * sides of the Redis sweep: a read that overlaps the sweep can no
        # * longer publish the pre-sweep value into L1 after the sweep ends.
        self._epoch: int = 0
        # * Monotonic mutation counter. A batch reader that is about to fill
        # * many keys at once captures it before its source read and skips
        # * the fill when it changed, so an invalidation that lands during
        # * the read cannot be undone by the batch.
        self._revision: int = 0
        # * Keys whose L2 delete is queued but may not have landed yet. An
        # * in-process reader must not republish the old L2 value while the
        # * tombstone/delete is still pending: the generation is already
        # * current for a read that starts after the invalidation, so only
        # * this local marker can close that window.
        self._pending_invalidations: set[Any] = set()
        # * Keys whose L2 write is queued but may not have landed yet. A
        # * read that starts after a local put can still see the OLD L2 value;
        # * promoting it into L1 would undo our own write. The marker is
        # * dropped when the queued write completes.
        self._pending_writes: set[Any] = set()

    # ── Sync operations (in-memory layer only) ── #

    def get(self, key: Any) -> T | object:
        """Return the in-memory cached value, or CACHE_MISS."""
        val = self._mem.get(key)
        if val is CACHE_MISS:
            metrics.record_miss()
        else:
            metrics.record_hit("l1")
        return val

    def put(self, key: Any, val: T) -> None:
        """Store in memory and enqueue an ordered Redis write."""
        self._mem.put(key, val)
        self._pending_invalidations.discard(key)
        self._revision += 1
        # * Advance the key's generation so a fetch that started before
        # * this write cannot overwrite the newer value with an older one.
        self._advance(key)
        self._redis_put_background(key, val)

    def put_local(self, key: Any, val: T) -> None:
        """Store in memory without publishing to Redis.

        Use for a value that is only a process-local hint and must not
        become shared state, such as a resolved identity that the source
        of truth already stores elsewhere. The generation still advances,
        so a fetch that started before the write cannot overwrite it.
        """
        self._mem.put(key, val)
        self._pending_invalidations.discard(key)
        self._revision += 1
        self._advance(key)

    def revision(self) -> int:
        """Return a counter that advances on every cache mutation."""
        return self._revision

    def invalidate(self, key: Any) -> None:
        """Remove from memory and enqueue an ordered Redis delete.

        Deletes for revocation prefixes (role, connection, group list,
        owner) and the locale caches are never droppable: a dropped
        revocation would leave other processes serving the revoked
        privilege or language until the key TTL.
        """
        self._mem.invalidate(key)
        metrics.record_invalidation()
        self._revision += 1
        # * Advance the key's generation so an in-flight fetch discards its
        # * stale result instead of resurrecting the revoked value.
        self._advance(key)
        if cfg.redis_url:
            self._pending_invalidations.add(key)
            rkey = self._rkey(key)
            # * Revocation prefixes need a cross-process marker before the
            # * delete: a failed tombstone must not be followed by a delete,
            # * or another process can promote the revoked L2 value. Display
            # * hints need no such marker, and leaving one for the full record
            # * TTL would suppress every later L2 fill for that key.
            mutation = (
                (lambda: self._redis_revoke(rkey, self._tombstone_key(key)))
                if self._critical_delete
                else (lambda: self._redis_delete(rkey))
            )
            task = redis_io.enqueue_redis_mutation(
                self._redis_prefix,
                mutation,
                droppable=not self._critical_delete,
            )
            self._watch_mutation(self._pending_invalidations, key, task)

    def clear(self) -> None:
        """Clear the in-memory layer (does not flush Redis keys)."""
        self._mem.clear()
        self._revision += 1
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
        this sweeps every key matching ``tcbot:<schema>:<prefix>:v2:*``. Do not call it in
        hot paths; it is designed for rare, high-impact invalidations only.
        The Redis sweep is never dropped by the mutation-queue bound, and the
        wait for it is bounded so a dead-Redis backlog cannot stall the caller
        (the sweep keeps running in the background and L1 is already clear).
        Individual commands rely on the client's socket timeout rather than
        ``wait_for``: cancelling a Redis command leaves its reply unread on the
        pooled connection.
        """
        self._mem.clear()
        metrics.record_invalidation()
        self._revision += 1
        # * Advance every known generation so an in-flight fetch discards
        # * its pre-sweep result, and bump the cache-wide epoch so a read
        # * that starts mid-sweep cannot republish into L1.
        self._epoch += 1
        for state in self._states.values():
            state.generation += 1
        pattern = f"{self._namespace()}:{self._redis_prefix}:v2:*"

        def _close_window() -> None:
            # * Close the window: reads that overlapped the sweep are
            # * discarded by the second epoch bump, and anything they
            # * already wrote into L1 is cleared here.
            self._mem.clear()
            self._epoch += 1
            self._revision += 1

        async def _clear_redis() -> None:
            try:
                live = await self._client()
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
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.debug(
                        "Redis clear_all failed for prefix %s: %s",
                        self._redis_prefix,
                        exc,
                    )
            finally:
                _close_window()

        task = redis_io.enqueue_redis_mutation(
            self._redis_prefix, _clear_redis, droppable=False
        )
        if task is None:
            # * The absolute queue ceiling can drop even a non-droppable
            # * sweep. Close the local window and make the missed L2 flush
            # * visible, instead of returning a silent success with stale
            # * privileges still cached in Redis.
            log.error(
                "Redis clear_all for prefix %s was dropped by the mutation queue; "
                "L2 keys were not swept and may serve stale values until their TTL.",
                self._redis_prefix,
            )
            _close_window()
            return
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
            metrics.record_hit("l1")
            return val
        rc = await self._client()
        if rc is None:
            metrics.record_miss()
            return CACHE_MISS
        rkey = self._rkey(key)
        # * Keep the key state alive for the read, so a concurrent write or
        # * invalidation advances the generation we captured instead of
        # * dropping the state and letting a stale L2 value back into L1.
        state = self._state(key)
        state.waiters += 1
        try:
            generation = state.generation
            epoch = self._epoch
            try:
                # * No ``wait_for`` here: cancelling a Redis command leaves its
                # * reply unread on a pooled connection, and the next command
                # * would read that stale reply. The client's socket timeout
                # * aborts a stalled op and disconnects the connection cleanly.
                raw = await rc.get(rkey)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _redis_mod.mark_op(ok=False)
                log.debug("Redis peek failed for %s: %s", rkey, exc)
                metrics.record_miss()
                return CACHE_MISS
            _redis_mod.mark_op(ok=True)
            if raw is None:
                metrics.record_miss()
                return CACHE_MISS
            try:
                loaded: T = _decode_redis_value(raw)
            except Exception as exc:
                log.debug("Redis payload decode failed for %s: %s", rkey, exc)
                metrics.record_miss()
                return CACHE_MISS
            # * A value invalidated while the read was in flight must not
            # * enter L1: it would serve the revoked value for a full TTL.
            metrics.record_hit("l2")
            if (
                state.generation == generation
                and self._epoch == epoch
                and key not in self._pending_invalidations
                and key not in self._pending_writes
            ):
                self._mem.put(key, loaded)
            return loaded
        finally:
            self._release(key, state)

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
                metrics.record_hit("l1")
                found[key] = cast("T", val)
        if not missing:
            return found
        rc = await self._client()
        if rc is None:
            for _ in missing:
                metrics.record_miss()
            return found
        # * The keys are read in bounded chunks, so a large batch cannot
        # * build one oversized command.
        for start in range(0, len(missing), _MGET_CHUNK_SIZE):
            chunk = missing[start : start + _MGET_CHUNK_SIZE]
            states = {key: self._state(key) for key in chunk}
            generations = {key: state.generation for key, state in states.items()}
            epoch = self._epoch
            for state in states.values():
                state.waiters += 1
            try:
                try:
                    raws = await rc.mget(*[self._rkey(key) for key in chunk])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _redis_mod.mark_op(ok=False)
                    log.debug(
                        "Redis mget failed for prefix %s: %s",
                        self._redis_prefix,
                        exc,
                    )
                    for _ in chunk:
                        metrics.record_miss()
                    return found
                _redis_mod.mark_op(ok=True)
                for key, raw in zip(chunk, raws, strict=False):
                    if raw is None:
                        metrics.record_miss()
                        continue
                    try:
                        loaded: T = _decode_redis_value(raw)
                    except Exception as exc:
                        log.debug(
                            "Redis payload decode failed for %s: %s",
                            self._rkey(key),
                            exc,
                        )
                        metrics.record_miss()
                        continue
                    metrics.record_hit("l2")
                    # * A pending local delete means this payload is revoked.
                    # * The single-key reader falls through to the source in
                    # * that case; a batch reader must not be less strict.
                    if key in self._pending_invalidations:
                        metrics.record_miss()
                        continue
                    if (
                        states[key].generation == generations[key]
                        and self._epoch == epoch
                        and key not in self._pending_writes
                    ):
                        self._mem.put(key, loaded)
                    found[key] = loaded
            finally:
                for key, state in states.items():
                    self._release(key, state)
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
            metrics.record_hit("l1")
            return cast("T", val)

        state = self._state(key)
        state.waiters += 1
        try:
            async with state.lock:
                # * Re-check L1 inside the lock to catch a winner that just populated it.
                val = self._mem.get(key)
                if val is not CACHE_MISS:
                    metrics.record_hit("l1")
                    return cast("T", val)
                generation = state.generation
                epoch = self._epoch

                # L2: Redis (bounded: a stalled Redis must not hold the hot path)
                rc = await self._client()
                if (
                    rc is not None
                    and key not in self._pending_invalidations
                    and (
                        not self._critical_delete or not await self._tombstoned(rc, key)
                    )
                ):
                    rkey = self._rkey(key)
                    try:
                        raw = await rc.get(rkey)
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
                                metrics.record_hit("l2")
                                # * The tombstone was checked before the GET.
                                # * Another process can revoke between that
                                # * check and this promotion, so confirm the
                                # * value is still live before writing L1.
                                if self._critical_delete and await self._tombstoned(
                                    rc, key
                                ):
                                    # ! CRITICAL: a remote revocation landed
                                    # * between the first check and this read.
                                    # * Returning the L2 value would authorize
                                    # * with a role that was just revoked.
                                    log.debug(
                                        "Discarding tombstoned Redis hit for %s", key
                                    )
                                    # * A revocation is authoritative: fall
                                    # * through to the source read instead of
                                    # * authorizing with a revoked value.
                                elif (
                                    state.generation != generation
                                    or self._epoch != epoch
                                    or key in self._pending_invalidations
                                    or key in self._pending_writes
                                ):
                                    # ! CRITICAL: a revocation that landed while
                                    # * the Redis read was in flight must fall
                                    # * through to the source; returning the old
                                    # * value would authorize with a revoked
                                    # * role. A pending write is different: its
                                    # * caller may still peek at the old L2 value,
                                    # * it just must not be promoted into L1.
                                    revoked = (
                                        state.generation != generation
                                        or self._epoch != epoch
                                        or key in self._pending_invalidations
                                    )
                                    log.debug(
                                        "Discarding stale Redis hit for "
                                        "invalidated key %s",
                                        key,
                                    )
                                    if not revoked:
                                        return loaded
                                else:
                                    # * An L2 hit is a cache write in L1; advance
                                    # * both counters so a concurrent peek or a
                                    # * batch reader that captured the old values
                                    # * cannot undo it.
                                    self._advance(key)
                                    self._revision += 1
                                    self._mem.put(key, loaded)
                                    return loaded

                # * L2 write is fire-and-forget and ordered FIFO against
                # * later invalidates; L1 already serves this value.
                # * Enqueued unconditionally so a reconnect before the
                # * write still lands the value.
                metrics.record_miss()
                val = await fetch()
                if (
                    state.generation != generation
                    or self._epoch != epoch
                    or key in self._pending_invalidations
                ):
                    # * The key was invalidated or overwritten while the
                    # * fetch was in flight (or a cache-wide sweep ran). The
                    # * fetched value predates the change, so caching it
                    # * would resurrect a revoked privilege for the whole
                    # * L1/L2 TTL. The caller still receives the value it
                    # * asked for.
                    log.debug("Discarding stale fetch for invalidated key %s", key)
                    return cast("T", val)
                # ! CRITICAL: a revocation in another process writes a Redis
                # * tombstone before its L2 delete. This DB snapshot predates
                # * it, so publishing here would restore the old value for the
                # * whole TTL. Local counters cannot observe that write.
                if self._critical_delete:
                    rc = await self._client()
                    if rc is not None and await self._tombstoned(rc, key):
                        log.debug("Discarding tombstoned fetch for %s", key)
                        return cast("T", val)
                if state.generation != generation or self._epoch != epoch:
                    # * invalidate() needs no lock and can land during the
                    # * tombstone await, so repeat the local check before the
                    # * publish to keep the last word with the writer.
                    log.debug("Discarding fetch invalidated mid-read for %s", key)
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
                epoch = self._epoch

                def _raced() -> bool:
                    return (
                        state.generation != generation
                        or self._epoch != epoch
                        or key in self._pending_invalidations
                    )

                val = await fetch()
                if _raced():
                    log.debug("Discarding stale refresh for invalidated key %s", key)
                    return val
                # * A local marker only covers this process. A revocation in
                # * another process writes a Redis tombstone before its delete;
                # * publishing after that point would resurrect the old value
                # * in L2 for the whole TTL. get_or_fetch already checks this.
                if self._critical_delete:
                    rc = await self._client()
                    if rc is not None and await self._tombstoned(rc, key):
                        log.debug("Discarding refresh for tombstoned key %s", key)
                        return val
                # ! CRITICAL: invalidate() is synchronous and needs no lock, so
                # * it can land during the awaits above. Publishing without this
                # * second check would restore a revoked privilege into L1.
                if _raced():
                    log.debug("Discarding refresh invalidated mid-read for %s", key)
                    return val
                self._publish(key, val)
                return val
        finally:
            self._release(key, state)

    # ── Internal helpers ── #

    def _release_marker_after_ttl(self, marker: set[Any], key: Any) -> None:
        """Hold a pending marker for as long as a stale L2 value can live."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            marker.discard(key)
        else:
            loop.call_later(self._redis_ttl, marker.discard, key)

    def _watch_mutation(
        self,
        marker: set[Any],
        key: Any,
        task: asyncio.Task[object] | None,
    ) -> None:
        """Keep *key* marked until its queued L2 mutation actually succeeds.

        A task finishing is not proof that it reached Redis: every mutation
        helper returns early when no usable client exists, and a cancelled
        task never runs its command. Releasing the marker in either case
        would let a reader promote the old L2 value into L1 for the full TTL.
        """
        if task is None:
            self._release_marker_after_ttl(marker, key)
            return

        def _done(done: asyncio.Task[object]) -> None:
            landed = False
            if not done.cancelled():
                try:
                    landed = bool(done.result())
                except Exception as exc:
                    log.debug("Redis mutation for %s failed: %s", key, exc)
            if landed:
                marker.discard(key)
            else:
                self._release_marker_after_ttl(marker, key)

        task.add_done_callback(_done)

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
        # * Publishing is a write like put(): advance both counters so a
        # * peek() or a batch reader that captured the old values cannot
        # * republish stale data over the fetched result.
        self._advance(key)
        self._revision += 1
        self._mem.put(key, val)
        self._pending_invalidations.discard(key)
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
        self._pending_writes.add(key)
        task = redis_io.enqueue_redis_mutation(
            self._redis_prefix,
            lambda: self._redis_set_guarded(rkey, payload, self._tombstone_key(key)),
            droppable=not self._is_revocation,
        )
        self._watch_mutation(self._pending_writes, key, task)

    async def _client(self) -> Any:
        """Return the Redis client, reconnecting after a failed startup.

        The client is resolved through the redis_io module so a patched
        client keeps working; only a missing client triggers the
        reconnect, which the client module rate-limits.
        """
        rc = redis_io.usable_redis_client()
        if rc is None:
            # * A configured Redis that cannot serve this loop is an outage,
            # * even when no command reaches the driver to report one.
            if cfg.redis_url:
                _redis_mod.mark_op(ok=False)
            rc = await redis_io.acquire_redis_client()
        return rc

    @staticmethod
    def _namespace() -> str:
        # ! CRITICAL: every instance pointed at the same REDIS_URL shares the
        # ! L2 store. The schema is the tenant boundary: without it a
        # ! development instance can read or invalidate the production owner,
        # ! role, and connection entries.
        return f"tcbot:{cfg.db_schema}"

    def _rkey(self, key: Any) -> str:
        return f"{self._namespace()}:{self._redis_prefix}:v2:{key}"

    def _tombstone_key(self, key: Any) -> str:
        return f"{self._namespace()}:{self._redis_prefix}:v2:tombstone:{key}"

    async def _tombstoned(self, rc: Any, key: Any) -> bool:
        """Return True while another process has a pending revocation."""
        try:
            exists = await rc.exists(self._tombstone_key(key))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Redis tombstone check failed for %s: %s", key, exc)
            return False
        return bool(exists)

    async def _redis_revoke(self, rkey: str, tomb_key: str) -> bool:
        """Write the cross-process marker before deleting the L2 value."""
        if not await self._redis_tombstone(tomb_key):
            return False
        return await self._redis_delete(rkey)

    async def _redis_tombstone(self, rkey: str) -> bool:
        """Write the short-lived tombstone with the shared failure policy."""
        rc = await self._client()
        if rc is None:
            return False
        try:
            # * The marker must outlive any stale L2 value when the delete
            # * fails, otherwise another process can promote it after the
            # * short marker expires while the key still lives in Redis.
            await rc.set(rkey, "1", ex=max(_TOMBSTONE_TTL_S, self._redis_ttl))
        except Exception as exc:
            # * A failed revocation marker is an outage, not a cache miss.
            _redis_mod.mark_op(ok=False)
            log.debug("Redis tombstone write failed for %s: %s", rkey, exc)
            return False
        return True

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller."""
        self._enqueue_write(key, val)

    async def _redis_set_guarded(
        self, rkey: str, payload: str, tombstone_key: str
    ) -> bool:
        """Skip a queued write when another process revoked the key meanwhile.

        The value in *payload* was fetched before the remote revocation. Writing
        it after the remote delete would restore the revoked role or group flag
        for the full TTL. The tombstone is written before that delete and lives
        longer than the queue, so checking it at write time closes the window.
        """
        rc = await self._client()
        if rc is None:
            return False
        try:
            if await rc.exists(tombstone_key):
                log.debug("Skipping L2 write for tombstoned %s", rkey)
                # * The remote delete will clear the old value, so there is
                # * no stale write left to guard against locally.
                return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Tombstone guard before L2 write failed for %s: %s", rkey, exc)
        return await self._redis_set(rkey, payload)

    async def _redis_set(self, rkey: str, payload: str) -> bool:
        """Write one Redis value and keep failures observable but non-fatal.

        The client resolves at run time, not enqueue time: a reconnect
        between queueing and execution must not write through a dead pool.
        The client's socket timeout bounds the op; the call is not wrapped
        in ``wait_for`` because a cancelled Redis command leaves its reply
        unread on the pooled connection.
        """
        rc = await self._client()
        if rc is None:
            return False
        try:
            await rc.set(rkey, payload, ex=self._redis_ttl)
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis set failed for %s: %s", rkey, exc)
            return False
        _redis_mod.mark_op(ok=True)
        return True

    async def _redis_delete(self, rkey: str) -> bool:
        """Delete one Redis value and keep failures observable but non-fatal."""
        rc = await self._client()
        if rc is None:
            return False
        try:
            await rc.delete(rkey)
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis delete failed for %s: %s", rkey, exc)
            return False
        _redis_mod.mark_op(ok=True)
        return True
