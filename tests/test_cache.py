# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.database.cache.TTLCache and shared cache singletons."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

from tcbot.database.cache import (
    CACHE_MISS,
    TTLCache,
    active_groups_cache,
    connected_cache,
    effective_role_cache,
    owner_id_cache,
)


class TestCacheMissSentinel:
    def test_cache_miss_is_singleton(self):
        assert CACHE_MISS is CACHE_MISS

    def test_cache_miss_is_not_none(self):
        assert CACHE_MISS is not None

    def test_cache_miss_falsy_check(self):
        assert CACHE_MISS is not False


class TestTTLCacheGet:
    def test_get_missing_key_returns_sentinel(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        assert cache.get("missing") is CACHE_MISS

    def test_get_fresh_value(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("k", 42)
        assert cache.get("k") == 42

    def test_get_expired_returns_sentinel(self):
        cache: TTLCache[str] = TTLCache(ttl=0.01)
        cache.put("k", "v")
        time.sleep(0.02)
        assert cache.get("k") is CACHE_MISS

    def test_get_expired_removes_entry(self):
        cache: TTLCache[str] = TTLCache(ttl=0.01)
        cache.put("k", "v")
        time.sleep(0.02)
        cache.get("k")
        assert cache.get("k") is CACHE_MISS

    def test_get_none_is_valid_value(self):
        cache: TTLCache[None] = TTLCache(ttl=60.0)
        cache.put("k", None)
        result = cache.get("k")
        assert result is not CACHE_MISS
        assert result is None


class TestTTLCachePut:
    def test_put_and_retrieve(self):
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.put("key", "value")
        assert cache.get("key") == "value"

    def test_put_overwrites_existing(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("k", 1)
        cache.put("k", 2)
        assert cache.get("k") == 2

    def test_put_multiple_keys(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("a", 1)
        cache.put("b", 2)
        assert cache.get("a") == 1
        assert cache.get("b") == 2

    def test_put_refreshes_ttl(self):
        cache: TTLCache[str] = TTLCache(ttl=0.05)
        cache.put("k", "first")
        time.sleep(0.03)
        cache.put("k", "second")
        time.sleep(0.03)
        assert cache.get("k") == "second"


class TestTTLCacheInvalidate:
    def test_invalidate_existing(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("k", 1)
        cache.invalidate("k")
        assert cache.get("k") is CACHE_MISS

    def test_invalidate_missing_is_noop(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.invalidate("nonexistent")
        assert cache.get("nonexistent") is CACHE_MISS

    def test_invalidate_does_not_affect_other_keys(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.invalidate("a")
        assert cache.get("a") is CACHE_MISS
        assert cache.get("b") == 2


class TestTTLCacheClear:
    def test_clear_removes_all(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.clear()
        assert cache.get("a") is CACHE_MISS
        assert cache.get("b") is CACHE_MISS
        assert cache.get("c") is CACHE_MISS

    def test_clear_empty_is_noop(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.clear()
        assert cache.get("anything") is CACHE_MISS


class TestTTLCacheGetOrFetch:
    async def test_fetch_called_on_miss(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        fetch = AsyncMock(return_value=99)
        result = await cache.get_or_fetch("k", fetch)
        assert result == 99
        fetch.assert_awaited_once()

    async def test_cached_value_skips_fetch(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        cache.put("k", 42)
        fetch = AsyncMock(return_value=99)
        result = await cache.get_or_fetch("k", fetch)
        assert result == 42
        fetch.assert_not_awaited()

    async def test_fetched_value_is_cached(self):
        cache: TTLCache[int] = TTLCache(ttl=60.0)
        fetch = AsyncMock(return_value=7)
        await cache.get_or_fetch("k", fetch)
        fetch2 = AsyncMock(return_value=999)
        result = await cache.get_or_fetch("k", fetch2)
        assert result == 7
        fetch2.assert_not_awaited()

    async def test_none_result_is_cached(self):
        cache: TTLCache[None] = TTLCache(ttl=60.0)
        fetch = AsyncMock(return_value=None)
        result = await cache.get_or_fetch("k", fetch)
        assert result is None
        await cache.get_or_fetch("k", fetch)
        fetch.assert_awaited_once()


class TestSharedSingletons:
    def test_effective_role_cache_is_ttl_cache(self):
        assert isinstance(effective_role_cache, TTLCache)

    def test_connected_cache_is_ttl_cache(self):
        assert isinstance(connected_cache, TTLCache)

    def test_active_groups_cache_is_ttl_cache(self):
        assert isinstance(active_groups_cache, TTLCache)

    def test_owner_id_cache_is_ttl_cache(self):
        assert isinstance(owner_id_cache, TTLCache)

    def test_singletons_are_distinct_instances(self):
        caches = [
            effective_role_cache,
            connected_cache,
            active_groups_cache,
            owner_id_cache,
        ]
        assert len(set(id(c) for c in caches)) == 4
