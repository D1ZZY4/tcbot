# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
In-process TTL cache - shared singletons for hot-path DB call elimination
* Provides lightweight in-memory caching with automatic expiration
* Eliminates repeated database queries for frequently accessed data
* All caches are thread-safe within asyncio's cooperative multitasking
* Multiple shared singleton instances used throughout the application
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

# * Public sentinel - use ``val is CACHE_MISS`` to detect a cache miss.
# * Distinct from None because None is a valid cache value (e.g. user has no role).
CACHE_MISS: object = object()


# ───────────────────────── TTL Cache Class ──────────────────────── #
# * Core cache implementation with TTL (time-to-live) expiration
# * Designed specifically for asyncio applications - no locks needed

class TTLCache:
    """
    Single-process in-memory TTL cache for asyncio-based code.
    * All operations are synchronous - no locks needed because asyncio is cooperative and only one coroutine runs at a time on the event loop.
    * ``get_or_fetch`` is the primary interface for most use cases
    * ``get`` / ``put`` / ``invalidate`` available for fine-grained control
    * Uses slots for memory efficiency and faster attribute access
    """

    __slots__ = ("_ttl", "_store")

    def __init__(self, ttl: float) -> None:
        self._ttl: float = ttl
        self._store: dict[Any, tuple[Any, float]] = {}

    def get(self, key: Any) -> Any:
        """
        Return the cached value, or ``CACHE_MISS`` if absent or expired.
        * Automatically purges expired entries when accessed
        * Uses monotonic time for accurate expiration calculations
        """
        entry = self._store.get(key, CACHE_MISS)
        if entry is CACHE_MISS:
            return CACHE_MISS
        val, exp = entry
        if time.monotonic() > exp:
            del self._store[key]
            return CACHE_MISS
        return val

    def put(self, key: Any, val: Any) -> None:
        """
        Store *val* under *key* for ``ttl`` seconds.
        * Sets expiration timestamp based on the cache's TTL
        * Overwrites any existing value for the same key
        """
        self._store[key] = (val, time.monotonic() + self._ttl)

    def invalidate(self, key: Any) -> None:
        """
        Remove *key* from the cache (no-op if absent or already expired).
        * Used for manual cache invalidation when data changes
        * Safe to call even if the key doesn't exist in the cache
        """
        self._store.pop(key, None)

    def clear(self) -> None:
        """
        Remove all entries immediately.
        * Complete cache flush - deletes everything in the store
        * Used when bulk invalidation is needed
        """
        self._store.clear()

    async def get_or_fetch(
        self,
        key: Any,
        fetch: Callable[[], Awaitable[Any]],
    ) -> Any:
        """
        Return cached value, or call *fetch()*, cache the result, and return it.
        * Primary interface for most cache usage
        * Only calls fetch() on cache miss to avoid redundant DB queries
        * Automatically caches the fetched value for future requests
        """
        val = self.get(key)
        if val is not CACHE_MISS:
            return val
        val = await fetch()
        self.put(key, val)
        return val


# ───────────────────── Shared Cache Singletons ──────────────────── #
# * Global cache instances used throughout the application
# * Each has specific TTLs tuned to their usage patterns
# * All are populated and invalidated by specific database modules

# 60-second per-user effective-role cache (str | None per user_id)
# Populated by roles_db.get_effective_role; invalidated on every role write
effective_role_cache: TTLCache = TTLCache(ttl=60.0)

# 120-second per-chat connection cache (bool per chat_id)
# Populated by groups_db.is_connected; invalidated on add/deactivate
connected_cache: TTLCache = TTLCache(ttl=120.0)

# 30-second whole-list active-groups cache (list[dict], single entry)
# Populated by groups_db.active_groups; invalidated on add/deactivate
active_groups_cache: TTLCache = TTLCache(ttl=30.0)
_ALL_GROUPS_KEY: str = "__all__"

# 300-second owner-ID cache (single int entry - ownership transfers are very rare)
# Populated by admins_db.get_owner_id; invalidated on set_owner / ensure_initial_owner
owner_id_cache: TTLCache = TTLCache(ttl=300.0)
_OWNER_KEY: str = "__owner__"
