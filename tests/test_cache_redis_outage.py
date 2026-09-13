# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis outage handling: L2 writes abort on timeout and mark liveness."""

from __future__ import annotations

import asyncio
import time

import pytest

import tcbot.database.cache as cache_mod
import tcbot.database.redis_client as redis_client_mod


class _FakeStalledRedis:
    """Redis double whose writes never complete."""

    async def set(self, *args: object, **kwargs: object) -> bool:
        await asyncio.sleep(60)
        return True

    async def delete(self, *args: object, **kwargs: object) -> int:
        await asyncio.sleep(60)
        return 1


class _FakeOkRedis:
    """Redis double whose writes succeed immediately."""

    async def set(self, *args: object, **kwargs: object) -> bool:
        return True

    async def delete(self, *args: object, **kwargs: object) -> int:
        return 1


@pytest.fixture(autouse=True)
def _reset_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate module liveness between tests."""
    monkeypatch.setattr(redis_client_mod, "_liveness", None)


def _cache() -> cache_mod.TwoLevelCache[object]:
    return cache_mod.TwoLevelCache(
        memory_ttl=60.0,
        redis_ttl=90.0,
        redis_prefix="test-redis-outage",
    )


def test_redis_set_times_out_and_marks_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_mod, "_REDIS_WRITE_TIMEOUT_S", 0.05)
    started = time.monotonic()
    asyncio.run(_cache()._redis_set(_FakeStalledRedis(), "k", "v"))
    assert time.monotonic() - started < 1.0
    assert redis_client_mod.liveness() is False


def test_redis_delete_times_out_and_marks_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_mod, "_REDIS_WRITE_TIMEOUT_S", 0.05)
    started = time.monotonic()
    asyncio.run(_cache()._redis_delete(_FakeStalledRedis(), "k"))
    assert time.monotonic() - started < 1.0
    assert redis_client_mod.liveness() is False


def test_redis_set_marks_healthy_on_success() -> None:
    asyncio.run(_cache()._redis_set(_FakeOkRedis(), "k", "v"))
    assert redis_client_mod.liveness() is True
