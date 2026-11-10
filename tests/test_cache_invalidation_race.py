# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cache invalidation must not be undone by an in-flight fetch."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database.cache.twolevel import TwoLevelCache


def _cache() -> TwoLevelCache[str]:
    """Return an L1-only cache (no Redis configured in the test session)."""
    return TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix="test")


def test_invalidation_during_a_fetch_does_not_resurrect_the_value() -> None:
    """A fetch that started before the invalidation must not repopulate L1."""

    async def _run() -> None:
        cache = _cache()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch() -> str:
            started.set()
            await release.wait()
            return "stale"

        async def _invalidate() -> None:
            await started.wait()
            cache.invalidate("k")
            release.set()

        result, _ = await asyncio.gather(
            cache.get_or_fetch("k", _fetch),
            _invalidate(),
        )
        assert result == "stale"
        # * The revoked value must not be cached: a later read has to hit
        # * the source again instead of serving the stale entry.
        calls = 0

        async def _counting_fetch() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        assert await cache.get_or_fetch("k", _counting_fetch) == "fresh"
        assert calls == 1

    asyncio.run(_run())


def test_explicit_put_during_a_fetch_wins() -> None:
    """A newer explicit write must not be overwritten by an older fetch."""

    async def _run() -> None:
        cache = _cache()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch() -> str:
            started.set()
            await release.wait()
            return "stale"

        async def _writer() -> None:
            await started.wait()
            cache.put("k", "fresh")
            release.set()

        result, _ = await asyncio.gather(cache.get_or_fetch("k", _fetch), _writer())
        assert result == "stale"
        assert cache.get("k") == "fresh"

    asyncio.run(_run())


def test_normal_fetch_still_populates_the_cache() -> None:
    """The invalidation guard must not break the ordinary cache-aside path."""

    async def _run() -> None:
        cache = _cache()

        async def _fetch() -> str:
            return "value"

        assert await cache.get_or_fetch("k", _fetch) == "value"
        assert cache.get("k") == "value"
        assert await cache.get_or_fetch("k", _fetch) == "value"

    asyncio.run(_run())


def test_clear_during_a_fetch_does_not_resurrect_the_value() -> None:
    """A cleared cache must not be repopulated by an in-flight fetch."""

    async def _run() -> None:
        cache = _cache()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch() -> str:
            started.set()
            await release.wait()
            return "stale"

        async def _clear() -> None:
            await started.wait()
            cache.clear()
            release.set()

        result, _ = await asyncio.gather(cache.get_or_fetch("k", _fetch), _clear())
        assert result == "stale"
        assert cache.get("k") != "stale"

    asyncio.run(_run())


@pytest.mark.parametrize("key", ["k"])
def test_cache_key_types(key: Any) -> None:
    """The cache accepts the string keys the role cache uses."""
    cache = _cache()
    cache.put(key, "value")
    assert cache.get(key) == "value"
