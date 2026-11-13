# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cache invalidation must not be undone by an in-flight fetch."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

from tcbot import cfg
from tcbot.database.cache import twolevel
from tcbot.database.cache.twolevel import TwoLevelCache


@pytest.fixture(autouse=True)
def _memory_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the cache on its in-memory layer for the whole module.

    The tests drive a fetch and a write against each other, so a value
    that Redis already holds would answer the fetch before the test can
    release it. The module is about the in-memory layer, so the second
    layer is switched off explicitly instead of relying on the session
    having no Redis configured.
    """
    monkeypatch.setattr(twolevel, "cfg", dataclasses.replace(cfg, redis_url=""))


def _cache() -> TwoLevelCache[str]:
    """Return an L1-only cache."""
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


def test_a_refresh_does_not_resurrect_an_invalidated_value() -> None:
    """A fresh read that lands after a demotion must not republish the role.

    The role cache serves the demotion through the fresh read path, so
    the value it carries can predate the write. Publishing it would keep
    the revoked role alive for the whole cache TTL.
    """

    async def _run() -> None:
        cache = _cache()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch() -> str:
            started.set()
            await release.wait()
            return "admin"

        async def _demote() -> None:
            await started.wait()
            cache.invalidate("k")
            release.set()

        result, _ = await asyncio.gather(cache.refresh("k", _fetch), _demote())
        assert result == "admin"
        assert cache.get("k") != "admin"

    asyncio.run(_run())


def test_a_refresh_publishes_an_unchanged_value() -> None:
    """The ordinary fresh read still refreshes the cached value."""

    async def _run() -> None:
        cache = _cache()

        async def _fetch() -> str:
            return "admin"

        assert await cache.refresh("k", _fetch) == "admin"
        assert cache.get("k") == "admin"

    asyncio.run(_run())


def test_an_invalidation_does_not_break_the_single_flight() -> None:
    """Concurrent readers of one key never run two source reads at once.

    The invalidation used to drop the per-key lock, so a reader that
    arrived after it started its own source read while the first one was
    still in flight.
    """

    async def _run() -> None:
        cache = _cache()
        started = asyncio.Event()
        release = asyncio.Event()
        in_flight = 0
        peak = 0

        async def _fetch() -> str:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            started.set()
            await release.wait()
            in_flight -= 1
            return "value"

        first = asyncio.create_task(cache.get_or_fetch("k", _fetch))
        await started.wait()
        cache.invalidate("k")
        second = asyncio.create_task(cache.get_or_fetch("k", _fetch))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)

        assert peak == 1

    asyncio.run(_run())
