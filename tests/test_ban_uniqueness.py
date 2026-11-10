# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-ban uniqueness: duplicate convergence and the canonical record."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from tcbot.database import bans_db, mongos


class _FakeResult:
    def __init__(self, modified_count: int = 0) -> None:
        self.modified_count = modified_count
        self.deleted_count = 0


class _FakeBans:
    """Minimal ``bans`` collection double for the migration and index paths."""

    def __init__(
        self,
        *,
        groups: list[dict[str, Any]] | None = None,
        duplicate_on_insert: bool = False,
    ) -> None:
        self.groups = groups or []
        self.updated: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.inserted: list[dict[str, Any]] = []
        self.insert_attempts = 0
        self.duplicate_on_insert = duplicate_on_insert

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _ = pipeline
        return self.groups

    def update_many(self, filt: dict[str, Any], update: dict[str, Any]) -> _FakeResult:
        self.updated.append((filt, update))
        return _FakeResult(modified_count=len(filt.get("ban_id", {}).get("$in", [])))

    def insert_one(self, doc: dict[str, Any]) -> Any:
        self.insert_attempts += 1
        if self.duplicate_on_insert:
            raise DuplicateKeyError("duplicate active ban")
        self.inserted.append(doc)
        return _FakeResult()

    def find_one(self, filt: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        _ = (filt, args, kwargs)
        return None

    def create_index(self, *args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        return "banned_user_id_1"


def test_migration_deactivates_the_duplicate_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every user with two active bans keeps exactly the canonical record."""
    collection = _FakeBans(
        groups=[
            {"_id": 42, "canonical": "new", "ban_ids": ["new", "old"]},
            {"_id": 43, "canonical": "only", "ban_ids": ["only"]},
        ]
    )
    monkeypatch.setattr(mongos, "col", lambda name: collection)

    asyncio.run(mongos._migrate_duplicate_active_bans())

    assert len(collection.updated) == 1
    filt, update = collection.updated[0]
    assert filt["banned_user_id"] == 42
    assert filt["ban_id"] == {"$in": ["old"]}
    assert update == {"$set": {"is_active": False}}


def test_migration_is_a_noop_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean collection is left untouched."""
    collection = _FakeBans(groups=[])
    monkeypatch.setattr(mongos, "col", lambda name: collection)

    asyncio.run(mongos._migrate_duplicate_active_bans())

    assert collection.updated == []


def test_create_ban_reuses_the_winning_record_on_a_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent ban loses the race and keeps the canonical record."""
    collection = _FakeBans(duplicate_on_insert=True)
    monkeypatch.setattr(bans_db, "_bans", lambda: collection)
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: "generated")

    async def _get_active_ban(user_id: int) -> dict[str, Any]:
        _ = user_id
        return {"ban_id": "winner", "banned_user_id": 42}

    monkeypatch.setattr(bans_db, "get_active_ban", _get_active_ban)

    doc = asyncio.run(bans_db.create_ban(42, "reason", 1, 0, 0))
    assert doc.get("ban_id") == "winner"
    # * The first insert hits the random-id retry, the second hits the
    # * one-active-ban constraint, so the loser reuses the winner.
    assert collection.insert_attempts == 2


def test_unique_partial_index_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active-ban uniqueness constraint is part of the index set."""
    created: list[dict[str, Any]] = []

    class _Indexable(_FakeBans):
        def create_index(self, *args: Any, **kwargs: Any) -> str:
            created.append({"keys": args[0], **kwargs})
            return "banned_user_id_1"

    monkeypatch.setattr(mongos, "col", lambda name: _Indexable())
    monkeypatch.setattr(mongos, "_drop_legacy_active_mutes_index", _noop)
    monkeypatch.setattr(mongos, "_migrate_duplicate_active_bans", _noop)

    asyncio.run(mongos.ensure_indexes())

    partial_indexes = [
        spec
        for spec in created
        if spec.get("partialFilterExpression") == {"is_active": True}
        and spec.get("unique") is True
    ]
    assert len(partial_indexes) == 1
    assert partial_indexes[0]["keys"] == [("banned_user_id", 1)]


async def _noop() -> None:
    """Stand-in for the migration pre-steps."""
    return
