# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-mute expiry rules verified against a real PostgreSQL server.

The stored expiry decides whether the bot can still manage a restriction,
so the merge rule has to hold against real database semantics and not
only against a hand-written double: a permanent mute must never be
downgraded to a timed one, and a timed mute must never shorten a longer
expiry.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from tcbot.database import engine as engine_module
from tcbot.database import mutes_db
from tcbot.database.base import active_mutes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def mute_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty active-mute table."""
    await engine_module.run(active_mutes.delete())
    yield postgres_db
    await engine_module.run(active_mutes.delete())


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp with second precision."""
    return datetime.now(UTC).replace(microsecond=0)


async def _stored_until(user_id: int) -> datetime | None:
    """Return the stored expiry of one user, or None for a permanent mute."""
    row = await engine_module.fetch_one(
        active_mutes.select().where(active_mutes.c.user_id == user_id)
    )
    assert row is not None
    value = row["until_date"]
    return value if isinstance(value, datetime) else None


async def test_timed_mute_stores_the_deadline(mute_db: str) -> None:
    """A first-time timed mute keeps its deadline."""
    deadline = _now() + timedelta(hours=1)

    await mutes_db.set_active_mute(42, until=deadline)

    assert await _stored_until(42) == deadline


async def test_permanent_mute_is_never_downgraded(mute_db: str) -> None:
    """A timed mute must not replace a stored permanent expiry.

    A permanent mute stores a null expiry, so the row survives the daily
    cleanup. Overwriting that null with a deadline would make the row
    expire and leave the bot unable to re-apply, report, or lift the
    mute.
    """
    await mutes_db.set_active_mute(42)
    await mutes_db.set_active_mute(42, until=_now() + timedelta(hours=1))

    assert await _stored_until(42) is None


async def test_permanent_mute_replaces_a_timed_one(mute_db: str) -> None:
    """A permanent mute upgrades a stored deadline."""
    await mutes_db.set_active_mute(42, until=_now() + timedelta(hours=1))
    await mutes_db.set_active_mute(42)

    assert await _stored_until(42) is None


async def test_timed_mute_never_shortens_an_expiry(mute_db: str) -> None:
    """A later deadline wins and an earlier one is ignored."""
    later = _now() + timedelta(hours=5)
    earlier = _now() + timedelta(hours=1)

    await mutes_db.set_active_mute(42, until=later)
    await mutes_db.set_active_mute(42, until=earlier)

    assert await _stored_until(42) == later

    await mutes_db.set_active_mute(42, until=later + timedelta(hours=1))

    assert await _stored_until(42) == later + timedelta(hours=1)


async def test_concurrent_mutes_keep_the_later_deadline(mute_db: str) -> None:
    """Two mutes racing for one user must not lose the later deadline.

    The upsert reads the stored row and writes the new deadline in one
    statement, so the second writer cannot miss the row and then lose
    its deadline to the first writer's insert.
    """
    earlier = _now() + timedelta(hours=1)
    later = _now() + timedelta(hours=5)

    await asyncio.gather(
        mutes_db.set_active_mute(42, until=earlier),
        mutes_db.set_active_mute(42, until=later),
    )

    assert await _stored_until(42) == later
