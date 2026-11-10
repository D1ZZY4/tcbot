# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis resilience: lazy reconnect after a failed startup and a bounded queue."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

import tcbot.database.cache as cache_mod
import tcbot.database.redis_client as redis_client_mod
from tcbot import cfg
from tcbot.database.cache.mutations import _REDIS_HARD_MAX_PENDING, _REDIS_MAX_PENDING


class _FakeRedis:
    """Redis double that records the calls it received."""

    def __init__(self) -> None:
        self.closed = False

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        _ = (args, kwargs)
        return True

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        _ = (args, kwargs)
        return 1


@pytest.fixture(autouse=True)
def _reset_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the Redis module state between tests."""
    monkeypatch.setattr(redis_client_mod, "_client", None)
    monkeypatch.setattr(redis_client_mod, "_pool", None)
    monkeypatch.setattr(redis_client_mod, "_reconnect_attempted_at", 0.0)
    monkeypatch.setattr(redis_client_mod, "_liveness", None)


def test_reconnect_is_skipped_without_a_configured_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No REDIS_URL means no reconnect attempt at all."""
    monkeypatch.setattr(
        redis_client_mod, "cfg", dataclasses.replace(cfg, redis_url=None)
    )
    assert asyncio.run(redis_client_mod.ensure_connected()) is None


def test_reconnect_recovers_a_dead_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis that was down at boot is re-established on the next attempt."""
    fake = _FakeRedis()
    monkeypatch.setattr(
        redis_client_mod,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://localhost:6379"),
    )
    monkeypatch.setattr(redis_client_mod, "_reconnect_attempted_at", 0.0)

    async def _connect(url: str) -> None:
        _ = url
        redis_client_mod._client = fake

    monkeypatch.setattr(redis_client_mod, "connect", _connect)

    client = asyncio.run(redis_client_mod.ensure_connected())
    assert client is fake


def test_reconnect_respects_the_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second attempt inside the backoff window is skipped."""
    monkeypatch.setattr(
        redis_client_mod,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://localhost:6379"),
    )
    monkeypatch.setattr(redis_client_mod, "_reconnect_attempted_at", 1e12)

    assert asyncio.run(redis_client_mod.ensure_connected()) is None


def test_reconnect_failure_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing reconnect degrades to the in-memory layer."""
    monkeypatch.setattr(
        redis_client_mod,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://localhost:6379"),
    )
    monkeypatch.setattr(redis_client_mod, "_reconnect_attempted_at", 0.0)

    async def _boom(url: str) -> None:
        _ = url
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client_mod, "connect", _boom)

    assert asyncio.run(redis_client_mod.ensure_connected()) is None


def test_cache_resolves_the_client_through_the_reconnect_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache reaches Redis again after a failed startup."""
    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis_client", lambda: None)
    monkeypatch.setattr(
        redis_client_mod,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://localhost:6379"),
    )

    async def _connect(url: str) -> None:
        _ = url
        redis_client_mod._client = fake

    monkeypatch.setattr(redis_client_mod, "connect", _connect)

    cache = cache_mod.TwoLevelCache(
        memory_ttl=60.0, redis_ttl=90.0, redis_prefix="test-reconnect"
    )
    asyncio.run(cache._redis_set("k", "v"))
    assert redis_client_mod.client() is fake


def test_queue_drops_a_droppable_op_past_the_soft_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A droppable op is dropped with a warning past the soft ceiling."""
    cache = cache_mod.TwoLevelCache(
        memory_ttl=60.0, redis_ttl=90.0, redis_prefix="test-queue-soft"
    )
    loop = asyncio.new_event_loop()
    try:
        tail_key = ("test-queue-soft", loop)
        cache_mod._redis_pending[tail_key] = _REDIS_MAX_PENDING
        task = cache._enqueue_redis_mutation(_noop, droppable=True)
        assert task is None
    finally:
        cache_mod._redis_pending.pop(("test-queue-soft", loop), None)
        loop.close()


def test_queue_drops_a_revocation_op_past_the_hard_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a revocation op is dropped past the hard ceiling."""
    cache = cache_mod.TwoLevelCache(
        memory_ttl=60.0, redis_ttl=90.0, redis_prefix="test-queue-hard"
    )
    loop = asyncio.new_event_loop()
    try:
        tail_key = ("test-queue-hard", loop)
        cache_mod._redis_pending[tail_key] = _REDIS_HARD_MAX_PENDING
        task = cache._enqueue_redis_mutation(_noop, droppable=False)
        assert task is None
    finally:
        cache_mod._redis_pending.pop(("test-queue-hard", loop), None)
        loop.close()


async def _noop() -> None:
    """Stand-in for a queued Redis operation."""
    return
