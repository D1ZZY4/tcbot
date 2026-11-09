# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""FIFO Redis mutations survive a cancelled predecessor."""

from __future__ import annotations

import asyncio

import pytest

import tcbot.database.cache as cache_mod
from tcbot.database.cache import mutations


class _FakeOkRedis:
    async def set(self, *args: object, **kwargs: object) -> bool:
        return True

    async def delete(self, *args: object, **kwargs: object) -> int:
        return 1


@pytest.fixture(autouse=True)
def _clean_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_mod, "_redis_client", lambda: _FakeOkRedis())
    mutations._redis_pending.clear()
    mutations._redis_tails.clear()
    mutations._redis_bg_tasks.clear()
    mutations._redis_drop_warned.clear()


def _cache() -> cache_mod.TwoLevelCache[str]:
    return cache_mod.TwoLevelCache(
        memory_ttl=60.0,
        redis_ttl=90.0,
        redis_prefix="test-fifo",
    )


def test_cancelled_predecessor_does_not_drop_successor() -> None:
    async def _scenario() -> list[str]:
        cache = _cache()
        ran: list[str] = []
        first_started = asyncio.Event()
        first_gate = asyncio.Event()

        async def _first() -> None:
            first_started.set()
            await first_gate.wait()
            ran.append("first")

        async def _second() -> None:
            ran.append("second")

        async def _third() -> None:
            ran.append("third")

        first = cache._enqueue_redis_mutation(_first)
        second = cache._enqueue_redis_mutation(_second, droppable=False)
        third = cache._enqueue_redis_mutation(_third, droppable=False)
        assert first is not None and second is not None and third is not None
        await first_started.wait()
        first_gate.set()
        await first
        second.cancel()
        await asyncio.gather(second, third, return_exceptions=True)
        return ran

    ran = asyncio.run(_scenario())
    assert "second" not in ran
    assert "third" in ran


def test_self_cancellation_still_aborts() -> None:
    async def _scenario() -> list[str]:
        cache = _cache()
        ran: list[str] = []
        second_started = asyncio.Event()
        second_gate = asyncio.Event()

        async def _first() -> None:
            ran.append("first")

        async def _second() -> None:
            second_started.set()
            await second_gate.wait()
            ran.append("second")

        first = cache._enqueue_redis_mutation(_first)
        second = cache._enqueue_redis_mutation(_second, droppable=False)
        assert first is not None and second is not None
        await first
        await second_started.wait()
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        return ran

    ran = asyncio.run(_scenario())
    assert ran == ["first"]
