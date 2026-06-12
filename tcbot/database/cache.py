# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Caching layer: in-process TTL cache (L1) + optional Redis (L2).

Architecture
------------
``TTLCache[T]``
    Pure in-memory cache.  All reads/writes are synchronous and sub-microsecond.
    Instances are used standalone for caches that do not need Redis.

``TwoLevelCache[T]``
    Wraps ``TTLCache[T]`` and adds an optional Redis L2 layer (via
    ``tcbot.database.redis_client``).  Public methods are drop-in compatible
    with ``TTLCache[T]``.

    *  ``get`` / ``put`` / ``invalidate`` / ``clear`` stay synchronous, operating
       on the in-memory layer.  ``put`` and ``invalidate`` also fire-and-forget a
       Redis write/delete to keep L2 eventually consistent.
    *  ``get_or_fetch`` is the primary hot-path: L1 → L2 → DB fetch, populating
       both layers on a miss.

Redis is optional.  When ``REDIS_URL`` is not set (or Redis is unreachable),
``TwoLevelCache`` degrades transparently to pure in-memory behaviour.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

import tcbot.database.redis_client as _redis_mod
from tcbot.database.documents import GroupDoc

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

# * Strong references to in-flight Redis background tasks; prevents GC before completion.
# * Mirrors the pattern used in __main__._asyncio_report_tasks and ban_flow._album_tasks.
_redis_bg_tasks: set[asyncio.Task[None]] = set()

# * Public sentinel; compare using ``is CACHE_MISS`` to detect a cache miss.
# * Distinct from None because None is a valid cache value (e.g. user has no role).
CACHE_MISS: object = object()


# ───────────────────────── TTL Cache Class ──────────────────────── #
# * Core single-process in-memory implementation with TTL expiration.
# * Designed for asyncio applications - no locks needed (single-threaded event loop).


class TTLCache[T]:
    """Single-process in-memory TTL cache for asyncio-based code."""

    __slots__ = ("_store", "_ttl")

    def __init__(self, ttl: float) -> None:
        """Initialise the cache with a time-to-live in seconds."""
        self._ttl: float = ttl
        self._store: dict[Any, tuple[T, float]] = {}

    def get(self, key: Any) -> T | object:
        """Return the cached value, or CACHE_MISS if absent or expired."""
        entry = self._store.get(key, CACHE_MISS)
        if entry is CACHE_MISS:
            return CACHE_MISS
        val, exp = entry
        if time.monotonic() > exp:
            del self._store[key]
            return CACHE_MISS
        return val

    def put(self, key: Any, val: T) -> None:
        """Store *val* under *key* for ttl seconds."""
        self._store[key] = (val, time.monotonic() + self._ttl)

    def invalidate(self, key: Any) -> None:
        """Remove *key* from the cache (no-op if absent or already expired)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries immediately."""
        self._store.clear()

    async def get_or_fetch(
        self,
        key: Any,
        fetch: Callable[[], Awaitable[T]],
    ) -> T:
        """Return cached value, or call *fetch()*, cache the result, and return it."""
        val = self.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)
        val = await fetch()
        self.put(key, val)
        return val


# ────────────────────── Two-Level Cache Class ───────────────────── #
# * Wraps TTLCache (L1) and adds Redis (L2) for distributed caching.
# * Drop-in compatible interface with TTLCache.


class TwoLevelCache[T]:
    """Two-level cache: in-memory L1 (fast) + Redis L2 (distributed, optional).

    When Redis is unavailable the cache degrades to pure in-memory behaviour
    identical to ``TTLCache``.  No configuration changes are required at call
    sites.
    """

    __slots__ = ("_mem", "_redis_prefix", "_redis_ttl")

    def __init__(self, memory_ttl: float, redis_ttl: float, redis_prefix: str) -> None:
        """Initialise with separate TTLs for each layer and a Redis key prefix."""
        self._mem: TTLCache[T] = TTLCache(ttl=memory_ttl)
        self._redis_ttl: int = max(1, int(redis_ttl))
        self._redis_prefix: str = redis_prefix

    # ── Sync operations (in-memory layer only) ── #

    def get(self, key: Any) -> T | object:
        """Return the in-memory cached value, or CACHE_MISS."""
        return self._mem.get(key)

    def put(self, key: Any, val: T) -> None:
        """Store in memory and fire-and-forget a Redis write."""
        self._mem.put(key, val)
        self._redis_put_background(key, val)

    def invalidate(self, key: Any) -> None:
        """Remove from memory and fire-and-forget a Redis delete."""
        self._mem.invalidate(key)
        self._redis_del_background(key)

    def clear(self) -> None:
        """Clear the in-memory layer (does not flush Redis keys)."""
        self._mem.clear()

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
        """
        # L1: in-memory
        val = self._mem.get(key)
        if val is not CACHE_MISS:
            return cast("T", val)

        # L2: Redis
        rc = _redis_client()
        if rc is not None:
            rkey = self._rkey(key)
            try:
                raw = await rc.get(rkey)
                if raw is not None:
                    loaded: T = json.loads(raw)
                    self._mem.put(key, loaded)
                    return loaded
            except Exception as exc:
                log.debug("Redis get failed for %s: %s", rkey, exc)

        # L3: DB fetch
        val = await fetch()
        self._mem.put(key, val)
        if rc is not None:
            rkey = self._rkey(key)
            try:
                await rc.set(rkey, json.dumps(val), ex=self._redis_ttl)
            except Exception as exc:
                log.debug("Redis set failed for %s: %s", rkey, exc)

        return cast("T", val)

    # ── Internal helpers ── #

    def _rkey(self, key: Any) -> str:
        return f"tcbot:{self._redis_prefix}:{key}"

    def _redis_put_background(self, key: Any, val: T) -> None:
        """Fire-and-forget Redis write without blocking the caller."""
        rc = _redis_client()
        if rc is None:
            return
        rkey = self._rkey(key)
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(rc.set(rkey, json.dumps(val), ex=self._redis_ttl))
            _redis_bg_tasks.add(task)
            task.add_done_callback(_redis_bg_tasks.discard)
            task.add_done_callback(_log_redis_task_error)
        except RuntimeError:
            pass  # No running loop during shutdown

    def _redis_del_background(self, key: Any) -> None:
        """Fire-and-forget Redis key deletion without blocking the caller."""
        rc = _redis_client()
        if rc is None:
            return
        rkey = self._rkey(key)
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(rc.delete(rkey))
            _redis_bg_tasks.add(task)
            task.add_done_callback(_redis_bg_tasks.discard)
            task.add_done_callback(_log_redis_task_error)
        except RuntimeError:
            pass  # No running loop during shutdown


def _redis_client() -> Any:
    """Return the active Redis client instance, or None when Redis is not configured."""
    return _redis_mod.client()


def _log_redis_task_error(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Done-callback: log Redis background task errors without raising."""
    if not task.cancelled() and task.exception() is not None:
        log.debug("Redis background task failed: %s", task.exception())


# ───────────────────────── Cache TTL Constants ──────────────────────── #
# * Named TTL constants kept together so tuning is one-place-one-change.
# * Unit: seconds (float).

# Per-user effective-role: short enough to pick up role changes quickly.
_ROLE_CACHE_TTL_S: float = 60.0
_ROLE_REDIS_TTL_S: float = 90.0  # Redis TTL slightly longer than in-memory

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
)

# Per-chat connection cache (bool per chat_id)
# Populated by groups_db.is_connected; invalidated on add/deactivate
connected_cache: TwoLevelCache[bool] = TwoLevelCache(
    memory_ttl=_CONNECTION_CACHE_TTL_S,
    redis_ttl=_CONNECTION_REDIS_TTL_S,
    redis_prefix="conn",
)

# Whole-list active-groups cache (list[dict], single entry keyed by _ALL_GROUPS_KEY)
# Populated by groups_db.active_groups; invalidated on add/deactivate
active_groups_cache: TwoLevelCache[list[GroupDoc]] = TwoLevelCache(
    memory_ttl=_GROUPS_LIST_CACHE_TTL_S,
    redis_ttl=_GROUPS_LIST_REDIS_TTL_S,
    redis_prefix="groups",
)
_ALL_GROUPS_KEY: str = "__all__"

# Owner-ID cache (single int entry - ownership transfers are very rare)
# Populated by users_roles.get_owner_id; invalidated on set_owner / ensure_initial_owner
owner_id_cache: TwoLevelCache[int | None] = TwoLevelCache(
    memory_ttl=_OWNER_CACHE_TTL_S,
    redis_ttl=_OWNER_REDIS_TTL_S,
    redis_prefix="owner",
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
)
