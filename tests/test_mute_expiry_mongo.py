# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-mute expiry rules verified against a MongoDB query engine.

The stored expiry decides whether the bot can still manage a restriction,
and the TTL index deletes any row whose ``until_date`` is a past date. The
merge rule therefore has to hold against real MongoDB semantics, not only
against a hand-written double: a permanent mute must never be downgraded
to a timed one, and a timed mute must never shorten a longer expiry.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest

from tcbot.database import mutes_db


@pytest.fixture
def mongo_mutes() -> Any:
    """Return an active_mutes collection backed by the in-memory engine."""
    client = mongomock.MongoClient()
    collection = client["tcbot"]["active_mutes"]
    collection.create_index("user_id", unique=True)
    return collection


def _now() -> datetime:
    """Return a millisecond-aligned UTC timestamp.

    BSON stores datetimes with millisecond precision, so the values the
    test compares against must be aligned to it.
    """
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def test_timed_mute_stores_the_deadline(
    monkeypatch: pytest.MonkeyPatch, mongo_mutes: Any
) -> None:
    """A first-time timed mute keeps its deadline."""
    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: mongo_mutes)
    deadline = _now() + timedelta(hours=1)

    asyncio.run(mutes_db.set_active_mute(42, until=deadline))

    stored = mongo_mutes.find_one({"user_id": 42})
    assert stored is not None
    assert stored["until_date"] == deadline


def test_permanent_mute_is_never_downgraded(
    monkeypatch: pytest.MonkeyPatch, mongo_mutes: Any
) -> None:
    """A timed mute must not replace a stored permanent expiry.

    A permanent mute stores a null expiry, so the TTL index keeps the row.
    Overwriting that null with a deadline would make the row expire and
    leave the bot unable to re-apply, report, or lift the mute.
    """
    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: mongo_mutes)

    asyncio.run(mutes_db.set_active_mute(42))
    asyncio.run(mutes_db.set_active_mute(42, until=_now() + timedelta(hours=1)))

    stored = mongo_mutes.find_one({"user_id": 42})
    assert stored is not None
    assert stored["until_date"] is None


def test_permanent_mute_replaces_a_timed_one(
    monkeypatch: pytest.MonkeyPatch, mongo_mutes: Any
) -> None:
    """A permanent mute upgrades a stored deadline."""
    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: mongo_mutes)

    asyncio.run(mutes_db.set_active_mute(42, until=_now() + timedelta(hours=1)))
    asyncio.run(mutes_db.set_active_mute(42))

    stored = mongo_mutes.find_one({"user_id": 42})
    assert stored is not None
    assert stored["until_date"] is None


def test_timed_mute_never_shortens_an_expiry(
    monkeypatch: pytest.MonkeyPatch, mongo_mutes: Any
) -> None:
    """A later deadline wins and an earlier one is ignored."""
    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: mongo_mutes)
    later = _now() + timedelta(hours=5)
    earlier = _now() + timedelta(hours=1)

    asyncio.run(mutes_db.set_active_mute(42, until=later))
    asyncio.run(mutes_db.set_active_mute(42, until=earlier))
    stored = mongo_mutes.find_one({"user_id": 42})
    assert stored is not None
    assert stored["until_date"] == later

    asyncio.run(mutes_db.set_active_mute(42, until=later + timedelta(hours=1)))
    stored = mongo_mutes.find_one({"user_id": 42})
    assert stored is not None
    assert stored["until_date"] == later + timedelta(hours=1)
