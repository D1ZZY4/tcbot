# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member-cache write amplification: an unchanged profile must not be rewritten."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tcbot import database as db
from tcbot.database import engine as engine_module
from tcbot.database import users_cache
from tcbot.database.base import member_cache
from tcbot.database.cache import CACHE_MISS, user_mention_cache

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def member_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty member-cache table and a cold mention cache."""
    await engine_module.run(member_cache.delete())
    user_mention_cache.clear()
    yield postgres_db
    await engine_module.run(member_cache.delete())
    user_mention_cache.clear()


def _count_writes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count the profile writes the helper performs."""
    writes: list[int] = []
    real_run = users_cache.run

    async def _run(stmt: Any) -> int:
        writes.append(1)
        return await real_run(stmt)

    monkeypatch.setattr(users_cache, "run", _run)
    return writes


async def test_repeated_messages_write_once(
    member_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member who keeps chatting under one name must not be rewritten.

    The member-cache handler runs for every update. Without the mention
    cache being populated on write, every message would cost one database
    write and one queued Redis delete for a profile that never changed.
    """
    writes = _count_writes(monkeypatch)

    results = [
        await db.users_cache.harvest_user_identity(7, "alice", "Alice", "Smith")
        for _ in range(20)
    ]

    assert results[0] is True
    assert not any(results[1:]), "an unchanged profile must not be rewritten"
    assert len(writes) == 1


async def test_a_changed_name_is_written_again(
    member_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real identity change still reaches the database."""
    writes = _count_writes(monkeypatch)

    await db.users_cache.harvest_user_identity(7, "alice", "Alice", "Smith")
    await db.users_cache.harvest_user_identity(7, "alice", "Alicia", "Smith")

    assert len(writes) == 2
    stored = await db.users_cache.get_user(7)
    assert stored is not None
    assert stored.get("first_name") == "Alicia"


async def test_a_partial_write_invalidates_rather_than_lying(
    member_db: str,
) -> None:
    """A write that preserves the stored username must not cache a guess.

    The moderator paths pass ``username=None`` to mean "keep the stored
    value". Caching the incoming triple would claim a username the database
    never received.
    """
    await db.users_cache.upsert_user(7, None, "Alice")

    assert user_mention_cache.get(7) is CACHE_MISS
