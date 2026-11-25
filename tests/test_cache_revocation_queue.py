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
from tcbot.utils import metrics


class _FakeOkRedis:
    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        return 1


@pytest.fixture(autouse=True)
def _clean_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: _FakeOkRedis())
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
    redis_io._redis_cancellable.clear()
    redis_io._redis_running.clear()


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

        # * One non-droppable revocation writes the marker before the delete.
        # * The mention delete is droppable and dropped under saturation.
        assert redis_io._redis_pending[("role", loop)] == before_role + 1
        assert redis_io._redis_pending[("umention", loop)] == before_mention
        new_tasks = set(redis_io._redis_bg_tasks) - tasks_before
        assert len(new_tasks) == 1
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)

    asyncio.run(_scenario())


def test_a_locale_delete_survives_sat_queue() -> None:
    """A language change must reach every process under queue pressure."""

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        new_tasks: set[asyncio.Task[None]] = set()
        for prefix in ("ulocale", "glocale", "clocale"):
            cache = _cache(prefix)
            redis_io._redis_pending[(prefix, loop)] = redis_io._REDIS_MAX_PENDING
            before = redis_io._redis_pending[(prefix, loop)]
            tasks_before = set(redis_io._redis_bg_tasks)

            cache.invalidate(123)

            # * A locale read consults the cross-process tombstone, so the
            # * combined marker-and-delete operation is non-droppable.
            assert redis_io._redis_pending[(prefix, loop)] == before + 1
            new_tasks |= set(redis_io._redis_bg_tasks) - tasks_before
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


def test_a_critical_op_at_the_hard_ceiling_evicts_a_droppable_op() -> None:
    """A pending revocation must win over a queued display hint.

    At the hard ceiling the old path dropped the critical op itself, so a
    role revocation could be lost while a mention-cache write kept its
    slot. The hint is cancel-safe only before its Redis call starts, so
    the eviction targets a not-started task.
    """

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        tail = ("role", loop)
        stale_hint = asyncio.create_task(asyncio.sleep(3600))
        redis_io._redis_cancellable[tail] = [stale_hint]
        redis_io._redis_pending[tail] = redis_io._REDIS_HARD_MAX_PENDING
        before_evictions = metrics.snapshot()["evictions"]

        async def _op() -> None:
            return None

        task = redis_io.enqueue_redis_mutation("role", _op, droppable=False)

        assert task is not None
        await asyncio.sleep(0)
        assert stale_hint.cancelled()
        assert metrics.snapshot()["evictions"] == before_evictions + 1
        assert redis_io._redis_pending[tail] == redis_io._REDIS_HARD_MAX_PENDING + 1
        task.cancel()
        await asyncio.gather(task, stale_hint, return_exceptions=True)

    asyncio.run(_scenario())


def test_a_running_droppable_op_is_not_evicted() -> None:
    """Cancelling an in-flight Redis call would leave its reply unread."""

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        tail = ("role", loop)
        busy = asyncio.create_task(asyncio.sleep(3600))
        redis_io._redis_cancellable[tail] = [busy]
        redis_io._redis_running.add(busy)
        redis_io._redis_pending[tail] = redis_io._REDIS_HARD_MAX_PENDING
        before_drops = metrics.snapshot()["drops"]

        async def _op() -> None:
            return None

        task = redis_io.enqueue_redis_mutation("role", _op, droppable=False)

        assert task is None
        assert not busy.cancelled()
        assert metrics.snapshot()["drops"] == before_drops + 1
        busy.cancel()
        await asyncio.gather(busy, return_exceptions=True)

    asyncio.run(_scenario())


def test_the_absolute_ceiling_drops_even_a_revocation() -> None:
    """A dead Redis cannot grow the process memory without bound."""

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        tail = ("role", loop)
        redis_io._redis_pending[tail] = redis_io._REDIS_ABSOLUTE_MAX_PENDING
        before_drops = metrics.snapshot()["drops"]

        async def _op() -> None:
            return None

        task = redis_io.enqueue_redis_mutation("role", _op, droppable=False)

        assert task is None
        assert metrics.snapshot()["drops"] == before_drops + 1

    asyncio.run(_scenario())
