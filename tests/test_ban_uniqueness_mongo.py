# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-ban uniqueness verified against a MongoDB query engine.

The migration and the unique partial index depend on MongoDB semantics the
hand-written doubles cannot prove: the aggregation pipeline that groups the
active bans per user, and the partial unique index that only constrains the
active records. The in-memory MongoDB double runs the same query shapes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from tcbot.database import bans_db, mongos

_ACTIVE_UNIQUE_INDEX: list[tuple[str, int]] = [("banned_user_id", 1)]


@pytest.fixture
def mongo_bans() -> Any:
    """Return a bans collection backed by the in-memory MongoDB engine."""
    client = mongomock.MongoClient()
    return client["tcbot"]["bans"]


def _insert(
    collection: Any,
    *,
    user_id: int,
    ban_id: str,
    minutes: int = 0,
    active: bool = True,
) -> None:
    """Insert one ban record."""
    collection.insert_one(
        {
            "banned_user_id": user_id,
            "ban_id": ban_id,
            "timestamp": datetime.now(UTC) + timedelta(minutes=minutes),
            "is_active": active,
        }
    )


def test_migration_finds_only_the_users_with_duplicates(
    monkeypatch: pytest.MonkeyPatch, mongo_bans: Any
) -> None:
    """The pipeline reports one group per user that holds two active bans."""
    _insert(mongo_bans, user_id=42, ban_id="old", minutes=-5)
    _insert(mongo_bans, user_id=42, ban_id="new", minutes=0)
    _insert(mongo_bans, user_id=43, ban_id="only")

    monkeypatch.setattr(mongos, "col", lambda name: mongo_bans)
    asyncio.run(mongos._migrate_duplicate_active_bans())

    remaining = list(mongo_bans.find({"is_active": True}))
    assert {doc["ban_id"] for doc in remaining} == {"new", "only"}


def test_migration_keeps_the_canonical_newest_record(
    monkeypatch: pytest.MonkeyPatch, mongo_bans: Any
) -> None:
    """The surviving record is the newest, matching what get_active_ban returns."""
    _insert(mongo_bans, user_id=42, ban_id="old", minutes=-5)
    _insert(mongo_bans, user_id=42, ban_id="new", minutes=0)

    monkeypatch.setattr(mongos, "col", lambda name: mongo_bans)
    asyncio.run(mongos._migrate_duplicate_active_bans())

    active = list(mongo_bans.find({"is_active": True}))
    assert len(active) == 1
    assert active[0]["ban_id"] == "new"


def test_partial_unique_index_rejects_a_second_active_ban(
    mongo_bans: Any,
) -> None:
    """The database itself keeps one active ban per user."""
    mongo_bans.create_index(
        _ACTIVE_UNIQUE_INDEX,
        unique=True,
        partialFilterExpression={"is_active": True},
    )
    _insert(mongo_bans, user_id=42, ban_id="first")

    with pytest.raises(DuplicateKeyError):
        _insert(mongo_bans, user_id=42, ban_id="second")


def test_partial_unique_index_allows_inactive_history(
    mongo_bans: Any,
) -> None:
    """Deactivated bans stay in the collection without breaking the index."""
    mongo_bans.create_index(
        _ACTIVE_UNIQUE_INDEX,
        unique=True,
        partialFilterExpression={"is_active": True},
    )
    _insert(mongo_bans, user_id=42, ban_id="first", active=False)
    _insert(mongo_bans, user_id=42, ban_id="second", active=False)
    assert mongo_bans.count_documents({"banned_user_id": 42}) == 2


def test_deactivate_extra_active_bans_keeps_one_record(
    monkeypatch: pytest.MonkeyPatch, mongo_bans: Any
) -> None:
    """The cleanup helper deactivates the duplicates and keeps the canonical one."""
    _insert(mongo_bans, user_id=42, ban_id="old", minutes=-5)
    _insert(mongo_bans, user_id=42, ban_id="new", minutes=0)

    monkeypatch.setattr(bans_db, "_bans", lambda: mongo_bans)
    count = asyncio.run(bans_db.deactivate_extra_active_bans(42, "new"))

    assert count == 1
    active = list(mongo_bans.find({"is_active": True}))
    assert [doc["ban_id"] for doc in active] == ["new"]
    assert mongo_bans.count_documents({"banned_user_id": 42}) == 2


def test_create_ban_returns_the_canonical_record_when_the_race_is_lost(
    monkeypatch: pytest.MonkeyPatch, mongo_bans: Any
) -> None:
    """A concurrent ban for the same target must not fail the second ban.

    The partial unique index allows one active ban per user, so the second
    moderator to insert loses the race. The surviving record is canonical:
    the caller keeps it and the moderation continues instead of reporting a
    database failure.
    """
    mongo_bans.create_index(
        _ACTIVE_UNIQUE_INDEX,
        unique=True,
        partialFilterExpression={"is_active": True},
    )
    monkeypatch.setattr(bans_db, "_bans", lambda: mongo_bans)
    monkeypatch.setattr(bans_db, "get_active_ban", _active_ban_reader(mongo_bans))

    winner = asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0, "winnerid"))
    assert winner.get("ban_id") == "winnerid"

    loser = asyncio.run(bans_db.create_ban(42, "spam", 8, 2, 0, "loserid"))

    assert loser.get("ban_id") == "winnerid"
    assert mongo_bans.count_documents({"banned_user_id": 42}) == 1


def test_create_ban_still_fails_on_a_real_id_collision(
    monkeypatch: pytest.MonkeyPatch, mongo_bans: Any
) -> None:
    """An explicit id that is already taken must not be silently swapped.

    The caller reuses the id for the appeal link and the log patch, so
    handing back a different record would orphan those references.
    """
    mongo_bans.create_index(
        _ACTIVE_UNIQUE_INDEX,
        unique=True,
        partialFilterExpression={"is_active": True},
    )
    mongo_bans.create_index([("ban_id", 1)], unique=True)
    monkeypatch.setattr(bans_db, "_bans", lambda: mongo_bans)
    monkeypatch.setattr(bans_db, "get_active_ban", _active_ban_reader(mongo_bans))

    asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0, "takenid"))

    with pytest.raises(DuplicateKeyError):
        asyncio.run(bans_db.create_ban(99, "spam", 7, 1, 0, "takenid"))


def _active_ban_reader(mongo_bans: Any) -> Any:
    """Return a ``get_active_ban`` double backed by the collection."""

    async def _reader(target_id: int) -> Any:
        return mongo_bans.find_one({"banned_user_id": target_id, "is_active": True})

    return _reader
