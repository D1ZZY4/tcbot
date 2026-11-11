# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""In-process TTL cache with bounded size."""

from __future__ import annotations

import contextlib
from typing import Any

import cachetools as _cachetools

# * Distinct from None because None is a valid cached value; compare with ``is``.
CACHE_MISS: object = object()


class TTLCache[T]:
    """Single-process in-memory TTL cache backed by cachetools.TTLCache.

    Uses cachetools for automatic TTL expiry AND LRU eviction when *maxsize*
    is reached, preventing unbounded memory growth that would occur with a
    plain dict.

    This is the L1 layer only. The single-flight fetching that guards
    against a cache stampede lives in :class:`TwoLevelCache`, which owns
    the per-key locks for the L1 and L2 layers together.
    """

    __slots__ = ("_store",)

    def __init__(self, ttl: float, maxsize: int = 512) -> None:
        """Initialise the cache with a time-to-live in seconds and a maximum size."""
        self._store: _cachetools.TTLCache = _cachetools.TTLCache(
            maxsize=maxsize, ttl=ttl
        )

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

    def clear(self) -> None:
        """Remove all entries immediately."""
        self._store.clear()
