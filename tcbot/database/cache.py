# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""In-process TTL plus optional Redis two-level cache."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import cachetools as _cachetools
import msgspec
from bson import ObjectId

import tcbot.database.redis_client as _redis_mod
from tcbot.database.documents import GroupDoc
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = get_logger(__name__)


# ──────────────────────── Redis Payload Codec ─────────────────────── #
# * Tagged values preserve MongoDB scalar types across the Redis JSON boundary.
# * Encoded with msgspec (C-backed, faster than the stdlib json codec it
# * replaces); the wire shape is unchanged tagged JSON, so payloads written
# * by either codec read identically.
_MONGO_TYPE_KEY: str = "__tcbot_type__"
_MONGO_DATETIME_TYPE: str = "datetime"
_MONGO_OBJECT_ID_TYPE: str = "objectid"


def _msgspec_enc_hook(obj: Any) -> Any:
    """Fallback encoder for scalar types msgspec cannot handle natively.

    Mirrors the retired stdlib ``default()`` fallback: unknown values become
    strings rather than failing the write. ``datetime`` and ``ObjectId``
    never reach this hook (see :func:`_tag_scalars`); it only covers
    genuinely unexpected scalars.
    """
    try:
        return str(obj)
    except Exception:
        raise TypeError(
            f"Object of type {type(obj).__name__} is not JSON serializable"
        ) from None


def _tag_scalars(value: Any) -> Any:
    """Replace ``datetime``/``ObjectId`` with tagged JSON objects before encoding.

    msgspec encodes ``datetime`` natively as a bare RFC3339 string, which
    would lose the tagged shape the L2 type contract requires, so tag first
    in Python and let msgspec encode the plain structure at C speed. The
    wire shape stays identical to the retired stdlib codec. Non-string
    mapping keys stringify like ``json.dumps`` does.
    """
    if isinstance(value, datetime):
        return {_MONGO_TYPE_KEY: _MONGO_DATETIME_TYPE, "value": value.isoformat()}
    if isinstance(value, ObjectId):
        return {_MONGO_TYPE_KEY: _MONGO_OBJECT_ID_TYPE, "value": str(value)}
    if isinstance(value, dict):
        return {
            (k if isinstance(k, str) else str(k)): _tag_scalars(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_tag_scalars(v) for v in value]
    return value


def _restore_tagged(value: Any) -> Any:
    """Restore tagged MongoDB scalar values while tolerating legacy cache data.

    Bottom-up replay of the retired stdlib ``object_hook``: children restore
    first, then the exact-shape check runs on the parent, so payloads written
    by either codec decode identically. Only exact-shape mappings (exactly
    the tag key plus the value key) restore: a user-controlled dict that
    merely contains the tag key must never deserialize into a datetime or
    ObjectId.
    """
    if isinstance(value, dict):
        restored = {k: _restore_tagged(v) for k, v in value.items()}
        if set(restored.keys()) != {_MONGO_TYPE_KEY, "value"}:
            return restored
        value_type = restored.get(_MONGO_TYPE_KEY)
        raw_value = restored.get("value")
        if value_type == _MONGO_DATETIME_TYPE and isinstance(raw_value, str):
            try:
                return datetime.fromisoformat(raw_value)
            except ValueError:
                return restored
        if value_type == _MONGO_OBJECT_ID_TYPE and isinstance(raw_value, str):
            try:
                return ObjectId(raw_value)
            except Exception:
                return restored
        return restored
    if isinstance(value, list):
        return [_restore_tagged(v) for v in value]
    return value


def _decode_redis_value(raw: str) -> Any:
    """Deserialize one Redis string via msgspec, restoring tagged scalars."""
    return _restore_tagged(msgspec.json.decode(raw))


# * Strong references to in-flight Redis background tasks; prevents GC before completion.
# * Mirrors the pattern used in __main__._asyncio_report_tasks and ban_flow flush tasks.
_redis_bg_tasks: set[asyncio.Task[None]] = set()
# * Redis namespaces must be ordered across cache instances sharing a prefix.
# * Scope by event loop because asyncio tasks cannot be awaited across loops.
_redis_tails: dict[tuple[str, asyncio.AbstractEventLoop], asyncio.Task[None]] = {}
# * Bound for queued mutations per (prefix, loop). Past this, new ops drop
# * with a warning: L2 is a TTL-bounded hint layer, so a dropped write only
# * extends cross-process staleness to the key TTL, while an unbounded
# * queue would grow memory and stall clear_all's shielded wait for the
# * whole serial backlog during an outage.
_REDIS_MAX_PENDING: int = 200
_redis_pending: dict[tuple[str, asyncio.AbstractEventLoop], int] = {}
_redis_drop_warned: set[tuple[str, asyncio.AbstractEventLoop]] = set()
# * Grace window for draining background mutations at shutdown before the
# * Redis pool closes underneath them.
_DRAIN_TIMEOUT_S: float = 5.0
# * Ceiling for one clear_all wait: the L2 sweep keeps running past it, so
# * a dead-Redis backlog delays the caller briefly instead of stalling a
# * privilege revocation path for the whole serial backlog.
_CLEAR_ALL_TIMEOUT_S: float = 10.0

# * Public sentinel; compare using ``is CACHE_MISS`` to detect a cache miss.
# * Distinct from None because None is a valid cache value (e.g. user has no role).
CACHE_MISS: object = object()

# * Upper bound for one Redis L2 read on the get_or_fetch hot path. The
# * socket default is far higher; without this cap a stalled Redis would
# * hold every L1 miss for seconds before the DB fetch runs. A timeout
# * falls through to the DB fetch, so correctness never depends on Redis.
_REDIS_GET_TIMEOUT_S: float = 1.0

# * Per-op ceiling for fire-and-forget L2 writes. The socket timeout is 10s
# * (redis_client) and mutations are serialized FIFO per prefix, so an
# * unreachable Redis would otherwise stall each queued write ~10s in turn.
_REDIS_WRITE_TIMEOUT_S: float = 2.0


# ───────────────────────── TTL Cache Class ──────────────────────── #
# * Core single-process in-memory implementation with TTL expiration.
# * Designed for asyncio applications - no locks needed (single-threaded event loop).


class TTLCache[T]:
    """Single-process in-memory TTL cache backed by cachetools.TTLCache.

    Uses cachetools for automatic TTL expiry AND LRU eviction when *maxsize* is
    reached, preventing unbounded memory growth that would occur with a plain dict.
    """

    __slots__ = ("_locks", "_store")

    def __init__(self, ttl: float, maxsize: int = 512) -> None:
        """Initialise the cache with a time-to-live in seconds and a maximum size."""
        self._store: _cachetools.TTLCache = _cachetools.TTLCache(
            maxsize=maxsize, ttl=ttl
        )
        self._locks: dict[Any, asyncio.Lock] = {}

    def get(self, key: Any) -> T | object:
        """Return the cached value, or CACHE_MISS if absent or expired."""
        try:
            return self._store[key]
        except KeyError:
            return CACHE_MISS

    def put(self, key: Any, val: T) -> None:
        """Store *val* under *key*; evicts LRU entry when maxsize is reached."""
        self._store[key] = val

    def invalidate(self, key: Any) -> None:
        """Remove *key* from the cache (no-op if absent or already expired)."""
        with contextlib.suppress(KeyError):
            del self._store[key]
        # * Drop the per-key lock so high-cardinality callers (e.g. member
        # * profile lookups) don't accumulate a stale lock for every user
        # * ever fetched. The lock object is only re-created on the next miss.
        self._locks.pop(key, None)

    def clear(self) -> None:
        """Remove all entries immediately."""
        self._store.clear()
        # * Locks from in-flight fetches remain in use; leave them. The next
        # * miss for any key will reuse the existing lock. Subsequent misses
        # * after the in-flight fetch completes will repopulate _locks with
        # * fresh entries, and stale ones for absent keys get cleared by
        # * invalidate(). A full lock purge is unnecessary here.
        # * If a true memory purge is required, restart the process.

    async def get_or_fetch(
        self,
        key: Any,
        fetch: Callable[[], Awaitable[T]],
    ) -> T:
        """Return cached value, or call *fetch()*, cache the result, and return it.

        A per-key ``asyncio.Lock`` serialises concurrent misses for the same key
        so that only one ``fetch()`` runs; the winner populates the cache and all
        waiters read the same result.  Different keys remain fully parallel.
        """
        val = self.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)

        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                val = self.get(key)
                if val is not CACHE_MISS:
                    return cast("T", val)
                val = await fetch()
                self.put(key, val)
                return val
        finally:
            # * Same unbounded-growth guard as TwoLevelCache.get_or_fetch:
            # * waiters hold their own reference, so popping here is safe.
            self._locks.pop(key, None)


# ────────────────────── Two-Level Cache Class ───────────────────── #
# * Wraps TTLCache (L1) and adds Redis (L2) for distributed caching.
# * Drop-in compatible interface with TTLCache.


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
        # * Per-key lock to serialise concurrent fetches for the same key
        # * across L1 + L2 + DB. Mirrors TTLCache.get_or_fetch semantics.
        # * Dropped per-fetch in get_or_fetch()'s finally block (plus in
        # * invalidate()) to prevent unbounded growth for high-cardinality
        # * callers (e.g. member profile lookups). clear() intentionally
        # * leaves locks alone: in-flight fetches may still hold them.
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
        # * Drop the per-key lock so high-cardinality callers (e.g. member
        # * profile lookups) don't accumulate a stale lock for every key
        # * ever fetched.
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
            live = _redis_client()
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
                    asyncio.shield(task), timeout=_CLEAR_ALL_TIMEOUT_S
                )
            except TimeoutError:
                log.warning(
                    "Redis clear_all for prefix %s still running after %ds; "
                    "continuing with L1 cleared.",
                    self._redis_prefix,
                    _CLEAR_ALL_TIMEOUT_S,
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
        # Fast path: in-memory hit, no lock needed.
        val = self._mem.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)

        # * Slow path: take a per-key lock so concurrent misses for the same
        # * key do not all run the DB fetch. Re-check L1 inside the lock to
        # * catch a winner that just populated it.
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                val = self._mem.get(key)
                if val is not CACHE_MISS:
                    return cast("T", val)

                # L2: Redis (bounded: a stalled Redis must not hold the hot path)
                rc = _redis_client()
                if rc is not None:
                    rkey = self._rkey(key)
                    try:
                        raw = await asyncio.wait_for(
                            rc.get(rkey), timeout=_REDIS_GET_TIMEOUT_S
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        _redis_mod.mark_op(ok=False)
                        log.debug("Redis get failed for %s: %s", rkey, exc)
                    else:
                        # * Any response (hit or miss) proves Redis is alive;
                        # * only a transport failure marks it down.
                        _redis_mod.mark_op(ok=True)
                        if raw is not None:
                            try:
                                loaded: T = _decode_redis_value(raw)
                            except Exception as exc:
                                # * Corrupt payload is a miss, not an outage:
                                # * fall through to the DB fetch without
                                # * touching the health flag.
                                log.debug(
                                    "Redis payload decode failed for %s: %s",
                                    rkey,
                                    exc,
                                )
                            else:
                                self._mem.put(key, loaded)
                                return loaded

                # L3: DB fetch. The L2 write is fire-and-forget: the value is
                # * already in L1, and awaiting the Redis SET would add a full
                # * Redis round-trip to every L1 miss. Ordering against later
                # * invalidates is preserved by the FIFO mutation chain; write
                # * errors still surface via the task's done-callback log.
                # * Enqueued unconditionally: the op resolves the client at
                # * run time and no-ops when Redis is absent, so a reconnect
                # * between the miss and the write still lands the value.
                val = await fetch()
                self._mem.put(key, val)
                rkey = self._rkey(key)
                try:
                    payload = msgspec.json.encode(
                        _tag_scalars(val), enc_hook=_msgspec_enc_hook
                    ).decode("utf-8")
                except Exception as exc:
                    # * L1 already serves this value: a serialization
                    # * failure must degrade to L1-only, never fail the
                    # * hot path that just fetched successfully.
                    log.debug("Redis payload encode failed for %s: %s", rkey, exc)
                else:
                    self._enqueue_redis_mutation(lambda: self._redis_set(rkey, payload))

                return cast("T", val)
        finally:
            # * Drop the per-key lock so a high-cardinality caller does not
            # * accumulate a stale lock for every key ever fetched. The next
            # * miss will create a fresh lock; the value itself is in
            # * ``self._mem`` already and is served by the fast path.
            self._locks.pop(key, None)

    # ── Internal helpers ── #

    def _rkey(self, key: Any) -> str:
        return f"tcbot:{self._redis_prefix}:v2:{key}"

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller."""
        rc = _redis_client()
        if rc is None:
            return
        rkey = self._rkey(key)
        # * L1 already serves this value: a serialization failure must
        # * skip the L2 write, never raise into a post-DB-write caller.
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
        rc = _redis_client()
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
        rc = _redis_client()
        if rc is None:
            return
        try:
            await asyncio.wait_for(
                rc.set(rkey, payload, ex=self._redis_ttl),
                timeout=_REDIS_WRITE_TIMEOUT_S,
            )
        except Exception as exc:
            _redis_mod.mark_op(ok=False)
            log.debug("Redis set failed for %s: %s", rkey, exc)
        else:
            _redis_mod.mark_op(ok=True)

    async def _redis_delete(self, rkey: str) -> None:
        """Delete one Redis value and keep failures observable but non-fatal."""
        rc = _redis_client()
        if rc is None:
            return
        try:
            await asyncio.wait_for(
                rc.delete(rkey),
                timeout=_REDIS_WRITE_TIMEOUT_S,
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


# ───────────────────────── Cache TTL Constants ──────────────────────── #
# * Named TTL constants kept together so tuning is one-place-one-change.
# * Unit: seconds (float).

# Per-user effective-role: short enough to pick up role changes quickly.
_ROLE_CACHE_TTL_S: float = 60.0
_ROLE_REDIS_TTL_S: float = 90.0  # Redis TTL slightly longer than in-memory

# ─────────────────────── Cache Maxsize Constants ─────────────────── #
# * Maximum in-memory entry counts per cache instance.
# * Sized to hold peak concurrent users/chats without unbounded growth.
_ROLE_CACHE_MAXSIZE: int = 2048  # roles: one entry per active user
_USER_MENTION_CACHE_MAXSIZE: int = (
    4096  # mention data: larger pool for check/stats lookups
)
_CONNECTED_CACHE_MAXSIZE: int = 512  # connection status: one entry per connected chat

# Per-chat connection status: medium window; connection changes are infrequent.
_CONNECTION_CACHE_TTL_S: float = 120.0
_CONNECTION_REDIS_TTL_S: float = 180.0

# Full active-groups list: short window; group add/remove is rare but must propagate.
_GROUPS_LIST_CACHE_TTL_S: float = 30.0
_GROUPS_LIST_REDIS_TTL_S: float = 45.0

# Owner ID: long window; ownership transfers are very rare.
_OWNER_CACHE_TTL_S: float = 300.0
_OWNER_REDIS_TTL_S: float = 360.0


# ───────────────────── Shared Cache Singletons ──────────────────── #
# * Global TwoLevelCache instances: L1 in-memory + L2 Redis (when available).
# * Each has separate TTLs tuned to its usage pattern and Redis prefix.
# * All are populated and invalidated by specific database modules.

# Per-user effective-role cache (str | None per user_id)
# Populated by users_roles.get_effective_role; invalidated on every role write
effective_role_cache: TwoLevelCache[str | None] = TwoLevelCache(
    memory_ttl=_ROLE_CACHE_TTL_S,
    redis_ttl=_ROLE_REDIS_TTL_S,
    redis_prefix="role",
    maxsize=_ROLE_CACHE_MAXSIZE,
)

# Per-chat connection cache (bool per chat_id)
# Populated by groups_db.is_connected; invalidated on add/deactivate
connected_cache: TwoLevelCache[bool] = TwoLevelCache(
    memory_ttl=_CONNECTION_CACHE_TTL_S,
    redis_ttl=_CONNECTION_REDIS_TTL_S,
    redis_prefix="conn",
    maxsize=_CONNECTED_CACHE_MAXSIZE,
)

# Whole-list active-groups cache (list[dict], single entry keyed by _ALL_GROUPS_KEY)
# Populated by groups_db.active_groups; invalidated on add/deactivate
active_groups_cache: TwoLevelCache[list[GroupDoc]] = TwoLevelCache(
    memory_ttl=_GROUPS_LIST_CACHE_TTL_S,
    redis_ttl=_GROUPS_LIST_REDIS_TTL_S,
    redis_prefix="groups",
    maxsize=4,
)
_ALL_GROUPS_KEY: str = "__all__"

# Owner-ID cache (single int entry - ownership transfers are very rare)
# Populated by users_roles.get_owner_id; invalidated on set_owner / ensure_initial_owner
owner_id_cache: TwoLevelCache[int | None] = TwoLevelCache(
    memory_ttl=_OWNER_CACHE_TTL_S,
    redis_ttl=_OWNER_REDIS_TTL_S,
    redis_prefix="owner",
    maxsize=4,
)
_OWNER_KEY: str = "__owner__"

# Per-user mention data cache (list [first_name, username] per user_id)
# Populated by users_cache.get_user_mention_data; invalidated on upsert_user
# JSON round-trip: tuple stored as list, caller casts back to tuple on read.
_USER_MENTION_CACHE_TTL_S: float = 300.0
_USER_MENTION_REDIS_TTL_S: float = 600.0

user_mention_cache: TwoLevelCache[list[str | None]] = TwoLevelCache(
    memory_ttl=_USER_MENTION_CACHE_TTL_S,
    redis_ttl=_USER_MENTION_REDIS_TTL_S,
    redis_prefix="umention",
    maxsize=_USER_MENTION_CACHE_MAXSIZE,
)
