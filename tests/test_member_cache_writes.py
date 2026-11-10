# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member-cache write amplification: an unchanged profile must not be rewritten."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.database import users_cache
from tcbot.database.cache import CACHE_MISS, user_mention_cache


class _FakeCollection:
    """Minimal collection double that counts write_one calls."""

    def __init__(self) -> None:
        self.write_calls: list[dict[str, Any]] = []

    def update_one(self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any):
        self.write_calls.append({"query": query, "update": update})

    def find_one(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest.fixture
def _fake_members(monkeypatch: pytest.MonkeyPatch) -> _FakeCollection:
    """Install a counting collection double and clear the mention cache."""
    collection = _FakeCollection()
    monkeypatch.setattr(users_cache, "_members", lambda: collection)
    user_mention_cache.clear()
    return collection


def test_repeated_messages_write_once(_fake_members: _FakeCollection) -> None:
    """A member who keeps chatting under one name must not be rewritten.

    The member-cache handler runs for every update. Before the mention cache
    was populated on write, every message cost one MongoDB update and one
    queued Redis delete for a profile that never changed.
    """

    async def _scenario() -> list[bool]:
        return [
            await db.users_cache.harvest_user_identity(7, "alice", "Alice", "Smith")
            for _ in range(20)
        ]

    results = asyncio.run(_scenario())

    assert results[0] is True
    assert not any(results[1:]), "an unchanged profile must not be rewritten"
    assert len(_fake_members.write_calls) == 1


def test_a_changed_name_is_written_again(_fake_members: _FakeCollection) -> None:
    """A real identity change still reaches the database."""

    async def _scenario() -> None:
        await db.users_cache.harvest_user_identity(7, "alice", "Alice", "Smith")
        await db.users_cache.harvest_user_identity(7, "alice", "Alicia", "Smith")

    asyncio.run(_scenario())

    assert len(_fake_members.write_calls) == 2


def test_a_partial_write_invalidates_rather_than_lying(
    _fake_members: _FakeCollection,
) -> None:
    """A write that preserves the stored username must not cache a guess.

    The moderator paths pass ``username=None`` to mean "keep the stored
    value". Caching the incoming triple would claim a username the database
    never received.
    """
    asyncio.run(db.users_cache.upsert_user(7, None, "Alice"))

    assert user_mention_cache.get(7) is CACHE_MISS
