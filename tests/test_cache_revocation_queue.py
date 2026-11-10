# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Revocation invalidations must survive mutation-queue saturation."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

import tcbot.database.cache as cache_mod
from tcbot import cfg
from tcbot.database.cache import redis_io
from tcbot.database.cache import twolevel as cache_twolevel


class _FakeOkRedis:
    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        return 1


@pytest.fixture(autouse=True)
def _clean_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_io, "redis_client", lambda: _FakeOkRedis())
    # * The cache only enqueues L2 mutations when Redis is configured: with
    # * no REDIS_URL there is no L2 to mutate, so the queue stays empty.
    monkeypatch.setattr(
        cache_twolevel,
        "cfg",
        dataclasses.replace(cfg, redis_url="redis://localhost:6379"),
    )
    redis_io._redis_pending.clear()
    redis_io._redis_tails.clear()
    redis_io._redis_bg_tasks.clear()
    redis_io._redis_drop_warned.clear()


def _cache(prefix: str) -> cache_mod.TwoLevelCache[Any]:
    return cache_mod.TwoLevelCache(memory_ttl=60.0, redis_ttl=90.0, redis_prefix=prefix)


def test_role_delete_survives_sat_queue_but_mention_drops() -> None:
    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        role_cache = _cache("role")
        mention_cache = _cache("umention")
        # Saturate both prefixes to the bound.
        redis_io._redis_pending[("role", loop)] = redis_io._REDIS_MAX_PENDING
        redis_io._redis_pending[("umention", loop)] = redis_io._REDIS_MAX_PENDING
        before_role = redis_io._redis_pending[("role", loop)]
        before_mention = redis_io._redis_pending[("umention", loop)]
        tasks_before = set(redis_io._redis_bg_tasks)

        role_cache.invalidate(123)
        mention_cache.invalidate(123)

        # Role delete enqueued despite the bound; mention delete dropped.
        assert redis_io._redis_pending[("role", loop)] == before_role + 1
        assert redis_io._redis_pending[("umention", loop)] == before_mention
        new_tasks = set(redis_io._redis_bg_tasks) - tasks_before
        assert len(new_tasks) == 1
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)

    asyncio.run(_scenario())


def test_role_put_survives_sat_queue() -> None:
    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        role_cache = _cache("role")
        redis_io._redis_pending[("role", loop)] = redis_io._REDIS_MAX_PENDING
        before = redis_io._redis_pending[("role", loop)]
        tasks_before = set(redis_io._redis_bg_tasks)

        role_cache.put(123, "admin")

        assert redis_io._redis_pending[("role", loop)] == before + 1
        new_tasks = set(redis_io._redis_bg_tasks) - tasks_before
        assert len(new_tasks) == 1
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)

    asyncio.run(_scenario())
