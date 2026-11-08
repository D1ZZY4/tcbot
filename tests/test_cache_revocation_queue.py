# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Revocation invalidations must survive mutation-queue saturation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import tcbot.database.cache as cache_mod
from tcbot.database.cache import mutations


class _FakeOkRedis:
    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        return 1


@pytest.fixture(autouse=True)
def _clean_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_mod, "_redis_client", lambda: _FakeOkRedis())
    mutations._redis_pending.clear()
    mutations._redis_tails.clear()
    mutations._redis_bg_tasks.clear()
    mutations._redis_drop_warned.clear()


def _cache(prefix: str) -> cache_mod.TwoLevelCache[Any]:
    return cache_mod.TwoLevelCache(memory_ttl=60.0, redis_ttl=90.0, redis_prefix=prefix)


def test_role_delete_survives_sat_queue_but_mention_drops() -> None:
    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        role_cache = _cache("role")
        mention_cache = _cache("umention")
        # Saturate both prefixes to the bound.
        mutations._redis_pending[("role", loop)] = mutations._REDIS_MAX_PENDING
        mutations._redis_pending[("umention", loop)] = mutations._REDIS_MAX_PENDING
        before_role = mutations._redis_pending[("role", loop)]
        before_mention = mutations._redis_pending[("umention", loop)]
        tasks_before = set(mutations._redis_bg_tasks)

        role_cache.invalidate(123)
        mention_cache.invalidate(123)

        # Role delete enqueued despite the bound; mention delete dropped.
        assert mutations._redis_pending[("role", loop)] == before_role + 1
        assert mutations._redis_pending[("umention", loop)] == before_mention
        new_tasks = set(mutations._redis_bg_tasks) - tasks_before
        assert len(new_tasks) == 1
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)

    asyncio.run(_scenario())


def test_role_put_survives_sat_queue() -> None:
    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        role_cache = _cache("role")
        mutations._redis_pending[("role", loop)] = mutations._REDIS_MAX_PENDING
        before = mutations._redis_pending[("role", loop)]
        tasks_before = set(mutations._redis_bg_tasks)

        role_cache.put(123, "admin")

        assert mutations._redis_pending[("role", loop)] == before + 1
        new_tasks = set(mutations._redis_bg_tasks) - tasks_before
        assert len(new_tasks) == 1
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)

    asyncio.run(_scenario())
