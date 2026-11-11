# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-ban uniqueness verified against a real PostgreSQL server.

The one-active-ban-per-user rule and the concurrent-ban race depend on
PostgreSQL semantics a hand-written double cannot prove: the partial
unique index only constrains the active records, and the loser of an
insert race reads the canonical record back instead of failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot.database import bans_db
from tcbot.database import engine as engine_module
from tcbot.database.base import bans

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty ban table with the partial unique index in place."""
    await engine_module.run(bans.delete())
    await _restore_active_index()
    yield postgres_db
    await engine_module.run(bans.delete())
    await _restore_active_index()


async def _restore_active_index() -> None:
    """Recreate the partial unique index over the (empty) ban table."""
    await engine_module.run(text("DROP INDEX IF EXISTS uq_bans_active_user"))
    await engine_module.run(
        text(
            "CREATE UNIQUE INDEX uq_bans_active_user "
            "ON bans (banned_user_id) WHERE is_active"
        )
    )


async def _insert_ban(
    user_id: int,
    ban_id: str,
    *,
    active: bool = True,
) -> None:
    """Insert one ban record straight into the table."""
    await engine_module.run(
        pg_insert(bans).values(
            ban_id=ban_id,
            banned_user_id=user_id,
            reason="spam",
            admin_user_id=7,
            is_active=active,
        )
    )


async def test_the_database_rejects_a_second_active_ban(
    ban_db: str,
) -> None:
    """The database itself keeps one active ban per user."""
    await _insert_ban(42, "first")

    with pytest.raises(IntegrityError) as excinfo:
        await _insert_ban(42, "second")

    assert engine_module.constraint_name(excinfo.value) == "uq_bans_active_user"


async def test_the_partial_index_allows_inactive_history(ban_db: str) -> None:
    """Deactivated bans stay in the table without breaking the index."""
    await _insert_ban(42, "first", active=False)
    await _insert_ban(42, "second", active=False)

    assert await bans_db.user_ban_count(42) == 2
    assert await bans_db.active_ban_count() == 0


async def test_the_live_schema_declares_the_named_constraints(
    ban_db: str,
) -> None:
    """The constraint the code reacts to exists in the running database."""
    rows = await engine_module.fetch_all(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'bans'"
        )
    )
    index_names = {str(row["indexname"]) for row in rows}

    assert "uq_bans_active_user" in index_names


async def test_create_ban_returns_the_canonical_record_when_the_race_is_lost(
    ban_db: str,
) -> None:
    """A concurrent ban for the same target must not fail the second ban.

    The partial unique index allows one active ban per user, so the second
    moderator to insert loses the race. The surviving record is canonical:
    the caller keeps it and the moderation continues instead of reporting a
    database failure.
    """
    winner = await bans_db.create_ban(42, "spam", 7, 1, 0, "winnerid")
    assert winner.get("ban_id") == "winnerid"

    loser = await bans_db.create_ban(42, "spam", 8, 2, 0, "loserid")

    assert loser.get("ban_id") == "winnerid"
    assert await bans_db.user_ban_count(42) == 1


async def test_create_ban_still_fails_on_a_real_id_collision(
    ban_db: str,
) -> None:
    """An explicit id that is already taken must not be silently swapped.

    The caller reuses the id for the appeal link and the log patch, so
    handing back a different record would orphan those references.
    """
    await bans_db.create_ban(42, "spam", 7, 1, 0, "takenid")

    with pytest.raises(IntegrityError) as excinfo:
        await bans_db.create_ban(99, "spam", 7, 1, 0, "takenid")

    assert engine_module.constraint_name(excinfo.value) == "uq_bans_ban_id"


async def _insert_legacy_duplicates(user_id: int) -> None:
    """Create the duplicate active bans a pre-index database could hold.

    The partial unique index is dropped for the insert, so the cleanup
    helper can be exercised against the legacy state it exists for. The
    fixture restores the index once the duplicates are gone.
    """
    await engine_module.run(text("DROP INDEX IF EXISTS uq_bans_active_user"))
    await _insert_ban(user_id, "old")
    await _insert_ban(user_id, "new")


async def test_deactivate_extra_active_bans_keeps_one_record(
    ban_db: str,
) -> None:
    """The cleanup helper deactivates the duplicates and keeps the canonical one."""
    await _insert_legacy_duplicates(42)

    count = await bans_db.deactivate_extra_active_bans(42, "new")

    assert count == 1
    active = await bans_db.get_active_ban(42)
    assert active is not None
    assert active.get("ban_id") == "new"
    assert await bans_db.user_ban_count(42) == 2


async def test_deactivate_extra_active_bans_touches_only_that_user(
    ban_db: str,
) -> None:
    """A user without duplicates keeps its single active ban."""
    await _insert_legacy_duplicates(42)
    await _insert_ban(43, "only")

    count = await bans_db.deactivate_extra_active_bans(42, "new")

    assert count == 1
    other = await bans_db.get_active_ban(43)
    assert other is not None
    assert other.get("ban_id") == "only"


async def test_the_canonical_record_is_the_active_one(ban_db: str) -> None:
    """The active ban is the record the profile and the appeal link name."""
    await _insert_ban(42, "old", active=False)
    await _insert_ban(42, "new")

    active = await bans_db.get_active_ban(42)

    assert active is not None
    assert active.get("ban_id") == "new"
