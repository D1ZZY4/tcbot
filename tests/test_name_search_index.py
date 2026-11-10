# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The member name search must stay indexable.

MongoDB cannot use an index for a case-insensitive regex, so the search
runs against lowercase mirror fields with a case-sensitive prefix query.
The migration fills the mirrors for the rows older releases wrote.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mongomock
import pytest

from tcbot.database import mongos, users_cache


@pytest.fixture
def mongo_members() -> Any:
    """Return a member_cache collection backed by the in-memory engine."""
    return mongomock.MongoClient()["tcbot"]["member_cache"]


def test_the_search_uses_the_lowercase_mirrors(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """The query must not use a case-insensitive regex on the raw fields."""
    mongo_members.insert_one(
        {
            "user_id": 7,
            "first_name": "Alice",
            "username": "Alice_1",
            "first_name_lower": "alice",
            "username_lower": "alice_1",
        }
    )
    monkeypatch.setattr(users_cache, "_members", lambda: mongo_members)

    found = asyncio.run(users_cache.search_by_name("ali"))

    assert [doc.get("user_id") for doc in found] == [7]


def test_the_search_matches_the_username_mirror(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """A username prefix is found through its own mirror."""
    mongo_members.insert_one(
        {
            "user_id": 8,
            "first_name": "Bob",
            "username": "Bobby",
            "first_name_lower": "bob",
            "username_lower": "bobby",
        }
    )
    monkeypatch.setattr(users_cache, "_members", lambda: mongo_members)

    found = asyncio.run(users_cache.search_by_name("BOB"))

    assert [doc.get("user_id") for doc in found] == [8]


def test_the_write_populates_the_mirrors(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """A profile write must carry the mirrors the search reads."""
    monkeypatch.setattr(users_cache, "_members", lambda: mongo_members)

    asyncio.run(users_cache.upsert_user(9, "Carol", "Carol", "Smith"))

    doc = mongo_members.find_one({"user_id": 9})
    assert doc is not None
    assert doc["first_name_lower"] == "carol"
    assert doc["username_lower"] == "carol"


def test_a_partial_write_leaves_the_username_mirror_alone(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """``username=None`` means "preserve", so the mirror must survive too."""
    monkeypatch.setattr(users_cache, "_members", lambda: mongo_members)

    asyncio.run(users_cache.upsert_user(9, "Carol", "Carol"))
    asyncio.run(users_cache.upsert_user(9, None, "Caroline"))

    doc = mongo_members.find_one({"user_id": 9})
    assert doc is not None
    assert doc["username"] == "Carol"
    assert doc["username_lower"] == "carol"
    assert doc["first_name_lower"] == "caroline"


def test_the_backfill_populates_the_mirrors(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """Rows written by older releases get their mirrors on startup."""
    mongo_members.insert_one(
        {"user_id": 11, "first_name": "Dave", "username": "Dave_x"}
    )
    monkeypatch.setattr(mongos, "col", lambda name: mongo_members)

    asyncio.run(mongos._migrate_member_cache_lower_names())

    doc = mongo_members.find_one({"user_id": 11})
    assert doc is not None
    assert doc["first_name_lower"] == "dave"
    assert doc["username_lower"] == "dave_x"


def test_the_backfill_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, mongo_members: Any
) -> None:
    """A second run must not change anything."""
    mongo_members.insert_one({"user_id": 12, "first_name": "Eve"})
    monkeypatch.setattr(mongos, "col", lambda name: mongo_members)

    asyncio.run(mongos._migrate_member_cache_lower_names())
    first = mongo_members.find_one({"user_id": 12})
    asyncio.run(mongos._migrate_member_cache_lower_names())
    second = mongo_members.find_one({"user_id": 12})

    assert first == second
