# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis outage handling: a failed L2 write is recorded and never raised."""

from __future__ import annotations

import asyncio

import pytest

import tcbot.database.cache as cache_mod
import tcbot.database.redis_client as redis_client_mod
from tcbot.database.cache import redis_io


class _FakeTimedOutRedis:
    """Redis double that raises the driver's socket timeout."""

    def __init__(self) -> None:
        self.completed = False

    async def set(self, *args: object, **kwargs: object) -> bool:
        _ = (args, kwargs)
        self.completed = True
        raise TimeoutError("Timeout reading from redis")

    async def delete(self, *args: object, **kwargs: object) -> int:
        _ = (args, kwargs)
        self.completed = True
        raise TimeoutError("Timeout reading from redis")


class _FakeOkRedis:
    """Redis double whose writes succeed immediately."""

    async def set(self, *args: object, **kwargs: object) -> bool:
        _ = (args, kwargs)
        return True

    async def delete(self, *args: object, **kwargs: object) -> int:
        _ = (args, kwargs)
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


def test_redis_set_marks_unhealthy_on_a_driver_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The socket timeout is recorded without being raised to the caller."""
    fake = _FakeTimedOutRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: fake)

    asyncio.run(_cache()._redis_set("k", "v"))

    assert fake.completed is True
    assert redis_client_mod.liveness() is False


def test_redis_delete_marks_unhealthy_on_a_driver_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed delete is recorded too."""
    fake = _FakeTimedOutRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: fake)

    asyncio.run(_cache()._redis_delete("k"))

    assert fake.completed is True
    assert redis_client_mod.liveness() is False


def test_redis_set_marks_healthy_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: _FakeOkRedis())
    asyncio.run(_cache()._redis_set("k", "v"))
    assert redis_client_mod.liveness() is True
