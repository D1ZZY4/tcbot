# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The ban insert must survive both uniqueness races, verified against PostgreSQL.

Two constraints can reject a ban insert: the unique identifier and the
one-active-ban-per-user rule. The identifier collision is retried with a
fresh identifier, and that retry can lose the other race. The retry must
take the same path as the first attempt instead of surfacing as a raw
write failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database import bans_db
from tcbot.database import engine as engine_module
from tcbot.database.base import bans

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.postgres]


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


async def _insert_ban(user_id: int, ban_id: str) -> None:
    """Insert one active ban record straight into the table."""
    await engine_module.run(
        pg_insert(bans).values(
            ban_id=ban_id,
            banned_user_id=user_id,
            reason="spam",
            admin_user_id=7,
            is_active=True,
        )
    )


def _fixed_ids(*ids: str) -> Any:
    """Return a generator that hands out the given identifiers in order."""
    remaining = list(ids)

    def _make() -> str:
        return remaining.pop(0) if remaining else "fallback-id"

    return _make


async def test_the_identifier_retry_keeps_the_canonical_ban(
    ban_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry that loses the active-ban race must reuse the stored record.

    The generated identifier collides, so the insert is retried with a
    fresh one. The retry then finds the target already banned, and the
    helper must hand back the canonical record instead of raising.
    """
    await _insert_ban(42, "canonical01")
    await _insert_ban(99, "collide001")
    monkeypatch.setattr(bans_db, "make_ban_id", _fixed_ids("collide001", "fresh0001"))

    record = await bans_db.create_ban(42, "spam", 7, 11, 12)

    assert record.get("ban_id") == "canonical01"
    assert record.get("banned_user_id") == 42


async def test_the_identifier_retry_stores_the_new_ban(
    ban_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry that wins both races must store the new record."""
    await _insert_ban(99, "collide001")
    monkeypatch.setattr(bans_db, "make_ban_id", _fixed_ids("collide001", "fresh0001"))

    record = await bans_db.create_ban(42, "spam", 7, 11, 12)

    assert record.get("ban_id") == "fresh0001"
    assert record.get("banned_user_id") == 42
