# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""In-process TTL cache - shared singletons for hot-path DB call elimination."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from tcbot.database.documents import GroupDoc

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# * Public sentinel; compare using is CACHE_MISS to detect a cache miss.
# * Distinct from None because None is a valid cache value (e.g. user has no role).
CACHE_MISS: object = object()


# ───────────────────────── TTL Cache Class ──────────────────────── #
# * Core cache implementation with TTL (time-to-live) expiration
# * Designed specifically for asyncio applications - no locks needed


class TTLCache[T]:
    """Single-process in-memory TTL cache for asyncio-based code."""

    __slots__ = ("_store", "_ttl")

    def __init__(self, ttl: float) -> None:
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


# ───────────────────────── Cache TTL Constants ──────────────────────── #
# * Named TTL constants kept together so tuning is one-place-one-change.
# * Unit: seconds (float).

# Per-user effective-role: short enough to pick up role changes quickly.
_ROLE_CACHE_TTL_S: float = 60.0

# Per-chat connection status: medium window; connection changes are infrequent.
_CONNECTION_CACHE_TTL_S: float = 120.0

# Full active-groups list: short window; group add/remove is rare but must propagate.
_GROUPS_LIST_CACHE_TTL_S: float = 30.0

# Owner ID: long window; ownership transfers are very rare.
_OWNER_CACHE_TTL_S: float = 300.0


# ───────────────────── Shared Cache Singletons ──────────────────── #
# * Global cache instances used throughout the application
# * Each has specific TTLs tuned to their usage patterns
# * All are populated and invalidated by specific database modules

# Per-user effective-role cache (str | None per user_id)
# Populated by users_roles.get_effective_role; invalidated on every role write
effective_role_cache: TTLCache[str | None] = TTLCache(ttl=_ROLE_CACHE_TTL_S)

# Per-chat connection cache (bool per chat_id)
# Populated by groups_db.is_connected; invalidated on add/deactivate
connected_cache: TTLCache[bool] = TTLCache(ttl=_CONNECTION_CACHE_TTL_S)

# Whole-list active-groups cache (list[dict], single entry keyed by _ALL_GROUPS_KEY)
# Populated by groups_db.active_groups; invalidated on add/deactivate
active_groups_cache: TTLCache[list[GroupDoc]] = TTLCache(ttl=_GROUPS_LIST_CACHE_TTL_S)
_ALL_GROUPS_KEY: str = "__all__"

# Owner-ID cache (single int entry - ownership transfers are very rare)
# Populated by users_roles.get_owner_id; invalidated on set_owner / ensure_initial_owner
owner_id_cache: TTLCache[int | None] = TTLCache(ttl=_OWNER_CACHE_TTL_S)
_OWNER_KEY: str = "__owner__"
