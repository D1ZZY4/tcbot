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
from tcbot.database import users_cache
from tcbot.database.cache import CACHE_MISS, redis_io, twolevel, user_mention_cache
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


@pytest.mark.parametrize("prefix", ["role", "ulocale"])
def test_a_cross_process_tombstone_forces_the_source_read(prefix: str) -> None:
    """A revocation marker written by another process must hide old L2 data."""

    class _TombstoneRedis:
        async def exists(self, key: str) -> int:
            return 1

        async def get(self, key: str) -> bytes:
            raise AssertionError("L2 must not be read while a tombstone is live")

    async def _run() -> None:
        cache = TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix=prefix)
        calls = 0

        async def _fetch() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        assert await cache.get_or_fetch("k", _fetch) == "fresh"
        assert calls == 1

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://x"))
        patch.setattr(redis_io, "usable_redis_client", lambda: _TombstoneRedis())
        asyncio.run(_run())


def test_a_local_invalidation_hides_stale_l2_until_its_delete_lands() -> None:
    """A read racing a queued delete must not republish the revoked L2 value.

    ``invalidate`` clears L1 and advances the generation at once, but the
    cross-process tombstone and the L2 delete are queued on the background
    FIFO. A reader that lands between those steps sees a live generation
    and no tombstone, so it can read the old L2 payload and put it back in
    L1 for a whole TTL.
    """

    class _StaleRedis:
        async def exists(self, key: str) -> int:
            _ = key
            return 0  # the queued tombstone has not landed yet

        async def get(self, key: str) -> str:
            _ = key
            return '"revoked"'

    async def _no_client() -> None:
        return None

    def _never_run(
        prefix: str, factory: Any, *, droppable: bool = True
    ) -> asyncio.Task[Any] | None:
        _ = (prefix, factory, droppable)
        return None

    async def _run() -> None:
        cache = TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix="role")
        fetch_calls = 0

        async def _fetch() -> str:
            nonlocal fetch_calls
            fetch_calls += 1
            return "fresh"

        cache.invalidate("k")
        assert await cache.get_or_fetch("k", _fetch) == "fresh"
        assert fetch_calls == 1

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://test")
        )
        patch.setattr(redis_io, "usable_redis_client", lambda: _StaleRedis())
        patch.setattr(redis_io, "acquire_redis_client", _no_client)
        patch.setattr(redis_io, "enqueue_redis_mutation", _never_run)
        asyncio.run(_run())


def test_a_tombstone_landing_during_a_db_fetch_is_not_overwritten() -> None:
    """A revocation from another process during the DB read must win.

    The DB snapshot predates the revocation. Without a post-fetch tombstone
    check the stale role is published to both caches for their full TTL.
    """

    class _GradualTombstone:
        def __init__(self) -> None:
            self.present = 0

        async def exists(self, key: str) -> int:
            _ = key
            return self.present

        async def get(self, key: str) -> None:
            _ = key
            return

    fake = _GradualTombstone()

    async def _no_client() -> None:
        return None

    def _never_run(prefix: str, factory: Any, *, droppable: bool = True) -> None:
        _ = (prefix, factory, droppable)
        return

    async def _run() -> None:
        cache = TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix="role")
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch() -> str:
            started.set()
            await release.wait()
            fake.present = 1
            return "revoked-role"

        async def _revoke() -> None:
            await started.wait()
            release.set()

        result, _ = await asyncio.gather(cache.get_or_fetch("k", _fetch), _revoke())
        assert result == "revoked-role"
        calls = 0

        async def _fresh() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        assert await cache.get_or_fetch("k", _fresh) == "fresh"
        assert calls == 1

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://test")
        )
        patch.setattr(redis_io, "usable_redis_client", lambda: fake)
        patch.setattr(redis_io, "acquire_redis_client", _no_client)
        patch.setattr(redis_io, "enqueue_redis_mutation", _never_run)
        asyncio.run(_run())


def test_a_locale_invalidation_enqueues_a_tombstone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A language change uses the same cross-process marker as a role."""
    calls: list[tuple[str, bool]] = []

    def _enqueue(prefix: str, factory: Any, *, droppable: bool = True) -> None:
        _ = factory
        calls.append((prefix, droppable))

    monkeypatch.setattr(
        twolevel,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://x"),
    )
    monkeypatch.setattr(redis_io, "enqueue_redis_mutation", _enqueue)

    TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix="ulocale").invalidate(7)

    assert calls == [("ulocale", False), ("ulocale", False)]


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


def test_a_read_that_overlaps_clear_all_does_not_repopulate_l1() -> None:
    """A read spanning the Redis sweep must discard its pre-sweep value.

    ``clear_all`` clears L1 before the sweep and again after it. A fetch
    that starts during the sweep and lands afterwards must not put the old
    value back: the cache-wide epoch changes on both sides of the sweep, so
    the publish is discarded. This is the ownership-transfer path, where a
    stale role would survive for a whole TTL.
    """

    class _BlockingRedis:
        """Redis double: scan blocks until the test releases it."""

        def __init__(self) -> None:
            self.scan_started = asyncio.Event()
            self.scan_release = asyncio.Event()

        async def scan(self, cursor: int, match: str = "", count: int = 100):
            _ = (cursor, match, count)
            self.scan_started.set()
            await self.scan_release.wait()
            return 0, []

        async def get(self, key: str) -> None:
            _ = key
            return

        async def set(self, *args: Any, **kwargs: Any) -> None:
            _ = (args, kwargs)

        async def unlink(self, *keys: str) -> int:
            _ = keys
            return 0

    fake = _BlockingRedis()

    async def _run() -> None:
        cache = TwoLevelCache(memory_ttl=60, redis_ttl=90, redis_prefix="role")
        fetch_started = asyncio.Event()
        fetch_release = asyncio.Event()

        async def _fetch() -> str:
            fetch_started.set()
            await fetch_release.wait()
            return "stale-founder"

        sweeping = asyncio.create_task(cache.clear_all())
        await fake.scan_started.wait()
        reading = asyncio.create_task(cache.get_or_fetch("owner", _fetch))
        await fetch_started.wait()
        fake.scan_release.set()
        await sweeping
        fetch_release.set()
        assert await reading == "stale-founder"
        assert cache.get("owner") is twolevel.CACHE_MISS

    async def _enqueue(
        prefix: str, factory: Any, *, droppable: bool = False
    ) -> asyncio.Task[Any]:
        _ = (prefix, droppable)
        return asyncio.create_task(factory())

    async def _no_client() -> None:
        return None

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://test")
        )
        patch.setattr(redis_io, "usable_redis_client", lambda: fake)
        patch.setattr(redis_io, "acquire_redis_client", _no_client)
        patch.setattr(redis_io, "enqueue_redis_mutation", _enqueue)
        asyncio.run(_run())


def test_a_batch_fill_discards_rows_invalidated_during_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch read must not undo an erasure that landed during its query.

    The batch readers fill many keys from one query. The cache revision is
    captured before the query, so an invalidation that lands while it runs
    makes the batch skip the fill instead of restoring the erased name.
    """

    async def _db_call(op: Any, **kwargs: Any) -> Any:
        return await op()

    async def _fetch_all(_stmt: Any) -> list[dict[str, Any]]:
        user_mention_cache.invalidate(7)
        return [
            {
                "user_id": 7,
                "first_name": "Alice",
                "username": "alice",
                "last_name": None,
            }
        ]

    monkeypatch.setattr(users_cache, "db_call", _db_call)
    monkeypatch.setattr(users_cache, "fetch_all", _fetch_all)

    async def _run() -> None:
        user_mention_cache.clear()
        result = await users_cache._mention_triples([7])
        assert result[7] == ["Alice", "alice", None]
        assert user_mention_cache.get(7) is CACHE_MISS

    asyncio.run(_run())
