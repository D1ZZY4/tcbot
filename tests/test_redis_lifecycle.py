# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis client lifecycle: one pool per endpoint, serialised connect and close."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

import tcbot.database.redis_client as redis_client_mod
from tcbot import cfg


class _FakePool:
    """Connection-pool double that records whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    """Redis client double: a reachable PING and a closable handle."""

    def __init__(self, pool: _FakePool) -> None:
        self.pool = pool
        self.closed = False

    async def ping(self) -> bool:
        await asyncio.sleep(0)
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_redis_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module singletons and point the client at a test URL."""
    monkeypatch.setattr(redis_client_mod, "_client", None)
    monkeypatch.setattr(redis_client_mod, "_pool", None)
    monkeypatch.setattr(redis_client_mod, "_connected_url", None)
    monkeypatch.setattr(redis_client_mod, "_client_loop", None)
    monkeypatch.setattr(redis_client_mod, "_pool_loop", None)
    monkeypatch.setattr(redis_client_mod, "_reconnect_attempted_at", 0.0)
    monkeypatch.setattr(redis_client_mod, "_liveness", None)
    monkeypatch.setattr(
        redis_client_mod,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://test:6379"),
    )


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> list[_FakePool]:
    """Capture every pool the client module builds."""
    created: list[_FakePool] = []

    def _from_url(url: str, **kwargs: Any) -> _FakePool:
        _ = (url, kwargs)
        pool = _FakePool()
        created.append(pool)
        return pool

    monkeypatch.setattr(redis_client_mod.aioredis.ConnectionPool, "from_url", _from_url)
    monkeypatch.setattr(
        redis_client_mod.aioredis,
        "Redis",
        lambda connection_pool: _FakeClient(connection_pool),
    )
    return created


def test_a_repeated_connect_keeps_the_first_pool(
    pools: list[_FakePool],
) -> None:
    """The same endpoint is never rebuilt while its client is usable."""

    async def _run() -> None:
        await redis_client_mod.connect("redis://test:6379")
        await redis_client_mod.connect("redis://test:6379")

    asyncio.run(_run())
    assert len(pools) == 1
    assert redis_client_mod.client() is not None


async def test_a_concurrent_reconnect_reuses_the_running_attempt(
    pools: list[_FakePool],
) -> None:
    """A cache write that reconnects during startup waits for the same pool."""
    await asyncio.gather(
        redis_client_mod.connect("redis://test:6379"),
        redis_client_mod.ensure_connected(),
    )

    assert len(pools) == 1
    assert redis_client_mod.client() is not None
    assert redis_client_mod.client_is_usable() is True


async def test_a_changed_endpoint_replaces_the_pool(
    pools: list[_FakePool],
) -> None:
    """A new URL closes the old pool and builds a new one."""
    await redis_client_mod.connect("redis://first:6379")
    await redis_client_mod.connect("redis://second:6379")

    assert len(pools) == 2
    assert pools[0].closed is True
    assert redis_client_mod._connected_url == "redis://second:6379"


async def test_close_releases_the_pool_and_its_url(
    pools: list[_FakePool],
) -> None:
    """Close releases both handles so the next connect starts clean."""
    await redis_client_mod.connect("redis://test:6379")
    await redis_client_mod.close()

    assert pools[0].closed is True
    assert redis_client_mod.client() is None
    assert redis_client_mod._connected_url is None

    await redis_client_mod.connect("redis://test:6379")
    assert len(pools) == 2
