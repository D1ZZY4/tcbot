# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""In-process TTL cache with per-key single-flight fetching."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, cast

import cachetools as _cachetools

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# * Distinct from None because None is a valid cached value; compare with ``is``.
CACHE_MISS: object = object()


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
        # * Drop the per-key lock so high-cardinality callers do not
        # * accumulate a stale lock for every key ever fetched.
        self._locks.pop(key, None)

    def clear(self) -> None:
        """Remove all entries immediately."""
        self._store.clear()
        # * In-flight fetches may still hold locks; leave them. The next
        # * miss reuses the existing lock, so no purge is needed here.

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
            # * Waiters hold their own reference, so popping here is safe
            # * and bounds lock growth for high-cardinality callers.
            self._locks.pop(key, None)
