# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Local cache markers must survive an L2 mutation that never landed.

A queued delete or write reports completion even when Redis has no usable
client and the command is skipped. Releasing the marker on task completion
let a later read promote the stale L2 value back into L1 for a full TTL.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

import tcbot.database.redis_client as redis_client_mod
from tcbot import cfg
from tcbot.database.cache import CACHE_MISS, redis_io, twolevel
from tcbot.database.cache.twolevel import TwoLevelCache


class _StaleRedis:
    """Redis double that still holds a value revoked by the local process."""

    def __init__(self) -> None:
        self.deletes = 0
        self.writes = 0

    async def exists(self, key: str) -> int:
        _ = key
        return 0

    async def get(self, key: str) -> str:
        _ = key
        return '"revoked"'

    async def delete(self, key: str) -> int:
        _ = key
        self.deletes += 1
        return 1

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        _ = (args, kwargs)
        self.writes += 1
        return True


def _queue(
    monkeypatch: pytest.MonkeyPatch, redis: _StaleRedis
) -> tuple[list[asyncio.Task[object]], dict[str, bool]]:
    """Run queued mutations immediately with a controllable outage window."""
    tasks: list[asyncio.Task[object]] = []
    outage: dict[str, bool] = {"active": True}

    def _enqueue(
        prefix: str, factory: Any, *, droppable: bool = True
    ) -> asyncio.Task[object]:
        _ = (prefix, droppable)
        task = asyncio.create_task(factory())
        tasks.append(task)
        return task

    async def _no_client() -> None:
        return None

    monkeypatch.setattr(
        twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://test")
    )
    monkeypatch.setattr(
        redis_io,
        "usable_redis_client",
        lambda: None if outage["active"] else redis,
    )
    monkeypatch.setattr(redis_io, "acquire_redis_client", _no_client)
    monkeypatch.setattr(redis_io, "enqueue_redis_mutation", _enqueue)
    return tasks, outage


async def _settle(tasks: list[asyncio.Task[object]], outage: dict[str, bool]) -> None:
    """Await the queued mutations, then reconnect for the reader."""
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0)
    outage["active"] = False


def test_a_delete_that_could_not_land_keeps_hiding_stale_l2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-client delete must not unblock the revoked L2 value."""

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )
        cache.invalidate(7)
        await _settle(tasks, outage)
        assert redis.deletes == 0

        calls = 0

        async def _fetch() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        assert await cache.get_or_fetch(7, _fetch) == "fresh"
        assert calls == 1

    redis = _StaleRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())


def test_a_write_that_could_not_land_keeps_hiding_stale_l2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-client write must not be undone by the older L2 value."""

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="conn"
        )
        cache.put(7, "fresh")
        await _settle(tasks, outage)
        assert redis.writes == 0
        # * Drop L1 so the read has to decide whether L2 is safe to promote.
        cache.clear()

        calls = 0

        async def _fetch() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        # * The peek contract may return the old L2 value, but a failed
        # * local write must never promote it into L1 for the full TTL.
        assert await cache.get_or_fetch(7, _fetch) == "revoked"
        assert cache.get(7) is CACHE_MISS
        assert calls == 0

    redis = _StaleRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())


def test_a_landed_delete_releases_the_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delete that reached Redis no longer blocks L2 reads."""

    class _LiveRedis(_StaleRedis):
        async def delete(self, key: str) -> int:
            _ = key
            self.deletes += 1
            return 1

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )
        outage["active"] = False
        cache.invalidate(7)
        await _settle(tasks, outage)
        assert redis.deletes == 1
        assert 7 not in cache._pending_invalidations

    redis = _LiveRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())


def test_a_revocation_landing_during_the_get_is_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tombstone written between the check and the GET wins over the L2 value."""

    class _LateTombstoneRedis(_StaleRedis):
        def __init__(self) -> None:
            super().__init__()
            self.exists_calls = 0

        async def exists(self, key: str) -> int:
            _ = key
            self.exists_calls += 1
            return 1 if self.exists_calls == 2 else 0

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )
        calls = 0

        async def _fetch() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        assert await cache.get_or_fetch(7, _fetch) == "fresh"
        assert calls == 1
        assert cache.get(7) == "fresh"

    redis = _LateTombstoneRedis()
    _tasks, outage = _queue(monkeypatch, redis)
    outage["active"] = False
    asyncio.run(_run())


def test_a_failed_tombstone_suppresses_the_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delete without its cross-process marker would expose a stale value."""

    class _TombstoneFailRedis(_StaleRedis):
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            if "tombstone:" in str(args[0] if args else ""):
                raise RuntimeError("tombstone write refused")
            return await super().set(*args, **kwargs)

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )
        outage["active"] = False
        cache.invalidate(7)
        await _settle(tasks, outage)
        assert redis.deletes == 0
        assert 7 in cache._pending_invalidations

    redis = _TombstoneFailRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())


def test_a_revocation_marker_outlives_the_l2_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed delete must not lose its marker while Redis still holds the key."""
    expiries: list[int] = []

    class _RecordingRedis(_StaleRedis):
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            if "tombstone:" in str(args[0] if args else ""):
                expiries.append(int(kwargs.get("ex", 0)))
            return await super().set(*args, **kwargs)

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )
        outage["active"] = False
        cache.invalidate(7)
        await _settle(tasks, outage)

    redis = _RecordingRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())
    assert expiries and expiries[0] >= 90


def test_a_display_hint_invalidation_does_not_block_later_l2_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A display-hint delete needs no tombstone that suppresses later writes."""
    written_keys: list[str] = []

    class _RecordingRedis(_StaleRedis):
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            written_keys.append(str(args[0]))
            return await super().set(*args, **kwargs)

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="umention"
        )
        outage["active"] = False
        cache.invalidate(7)
        await _settle(tasks, outage)
        cache.put(7, "fresh")
        await _settle(tasks, outage)

    redis = _RecordingRedis()
    tasks, outage = _queue(monkeypatch, redis)
    asyncio.run(_run())
    assert not any("tombstone:" in key for key in written_keys)
    assert any(key.endswith(":umention:v2:7") for key in written_keys)


def test_a_configured_redis_outage_without_a_client_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing client is an outage even when no command reaches the driver."""
    monkeypatch.setattr(redis_client_mod, "_liveness", None)
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: None)

    async def _no_client() -> None:
        return None

    monkeypatch.setattr(redis_io, "acquire_redis_client", _no_client)
    monkeypatch.setattr(
        twolevel, "cfg", dataclasses.replace(cfg, redis_url="redis://test")
    )

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="test"
        )

        async def _fetch() -> str:
            return "value"

        assert await cache.get_or_fetch(1, _fetch) == "value"

    asyncio.run(_run())
    assert redis_client_mod.liveness() is False
