# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared Redis keys are scoped to the PostgreSQL schema that owns the data."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from tcbot import cfg
from tcbot.database.cache import twolevel


def _cache() -> twolevel.TwoLevelCache[str]:
    return twolevel.TwoLevelCache(
        memory_ttl=60.0,
        redis_ttl=90.0,
        redis_prefix="role",
    )


def test_schema_separates_l2_keys(monkeypatch: Any) -> None:
    """Two deployments on one Redis must not share authorization entries."""
    cache = _cache()

    monkeypatch.setattr(twolevel, "cfg", dataclasses.replace(cfg, db_schema="public"))
    production_key = cache._rkey(42)
    production_tombstone = cache._tombstone_key(42)

    monkeypatch.setattr(
        twolevel, "cfg", dataclasses.replace(cfg, db_schema="development")
    )
    development_key = cache._rkey(42)
    development_tombstone = cache._tombstone_key(42)

    assert production_key == "tcbot:public:role:v2:42"
    assert development_key == "tcbot:development:role:v2:42"
    assert production_key != development_key
    assert production_tombstone != development_tombstone


def test_schema_separates_the_clear_all_sweep(monkeypatch: Any) -> None:
    """A sweep must not delete another schema's cached privileges."""
    cache = _cache()
    patterns: list[str] = []

    class _Redis:
        async def scan(self, cursor: int, match: str = "", count: int = 100) -> Any:
            patterns.append(match)
            return 0, []

    def _enqueue(_prefix: str, work: Any, *, droppable: bool = False) -> Any:
        async def _run() -> None:
            await work()

        return asyncio.create_task(_run())

    monkeypatch.setattr(twolevel.redis_io, "usable_redis_client", lambda: _Redis())
    monkeypatch.setattr(twolevel.redis_io, "enqueue_redis_mutation", _enqueue)

    monkeypatch.setattr(twolevel, "cfg", dataclasses.replace(cfg, db_schema="public"))
    asyncio.run(cache.clear_all())
    monkeypatch.setattr(
        twolevel, "cfg", dataclasses.replace(cfg, db_schema="development")
    )
    asyncio.run(cache.clear_all())

    assert patterns == [
        "tcbot:public:role:v2:*",
        "tcbot:development:role:v2:*",
    ]
