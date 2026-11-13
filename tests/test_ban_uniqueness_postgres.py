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

from tcbot import cfg
from tcbot.database import bans_db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_cases
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community."""
    await reset_community()
    await seed_users(7, 8, 42, 43, 99)
    await seed_chats(cfg.proofs[0])
    yield postgres_db
    await reset_community()


async def _insert_ban(
    user_id: int,
    ban_id: str,
    *,
    active: bool = True,
) -> None:
    """Insert one ban decision straight into the table."""
    case = (
        await engine_module.run_returning(
            pg_insert(moderation_cases)
            .values(
                subject_user_id=user_id,
                title="Raw ban",
                status="open",
                source="manual",
                opened_by_user_id=7,
                requires_evidence=False,
            )
            .returning(moderation_cases.c.id)
        )
    )[0]
    await engine_module.run(
        pg_insert(moderation_actions).values(
            action_type="ban",
            scope_type="community",
            target_user_id=user_id,
            actor_user_id=7,
            reason="spam",
            status="active" if active else "revoked",
            external_ref=ban_id,
            case_id=case["id"],
            # * The automated origin needs no archived proof, so the raw
            # * insert can file the decision without one.
            action_origin="automated",
        )
    )


async def test_the_database_rejects_a_second_active_ban(
    ban_db: str,
) -> None:
    """The database itself keeps one active ban per user."""
    await _insert_ban(42, "firstban01")

    with pytest.raises(IntegrityError) as excinfo:
        await _insert_ban(42, "secondban1")

    assert (
        engine_module.constraint_name(excinfo.value)
        == "uq_moderation_actions_active_ban"
    )


async def test_the_partial_index_allows_inactive_history(ban_db: str) -> None:
    """Revoked bans stay in the table without breaking the index."""
    await _insert_ban(42, "firstban01", active=False)
    await _insert_ban(42, "secondban1", active=False)

    assert await bans_db.user_ban_count(42) == 2
    assert await bans_db.active_ban_count() == 0


async def test_the_live_schema_declares_the_named_constraints(
    ban_db: str,
) -> None:
    """The constraint the code reacts to exists in the running database."""
    rows = await engine_module.fetch_all(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND tablename = 'moderation_actions'"
        )
    )
    index_names = {str(row["indexname"]) for row in rows}

    assert "uq_moderation_actions_active_ban" in index_names


async def test_create_ban_returns_the_canonical_record_when_the_race_is_lost(
    ban_db: str,
) -> None:
    """A concurrent ban for the same target must not fail the second ban.

    The partial unique index allows one active ban per user, so the second
    moderator to insert loses the race. The surviving record is canonical:
    the caller keeps it and the moderation continues instead of reporting a
    database failure.
    """
    winner = await bans_db.create_ban(42, "spam", 7, 1, 0, "winnerid01")
    assert winner.get("ban_id") == "winnerid01"

    loser = await bans_db.create_ban(42, "spam", 8, 2, 0, "loserid001")

    assert loser.get("ban_id") == "winnerid01"
    assert await bans_db.user_ban_count(42) == 1


async def test_create_ban_still_fails_on_a_real_id_collision(
    ban_db: str,
) -> None:
    """An explicit id that is already taken must not be silently swapped.

    The caller reuses the id for the appeal link and the log patch, so
    handing back a different record would orphan those references.
    """
    await bans_db.create_ban(42, "spam", 7, 1, 0, "takenid001")

    with pytest.raises(IntegrityError) as excinfo:
        await bans_db.create_ban(99, "spam", 7, 1, 0, "takenid001")

    assert (
        engine_module.constraint_name(excinfo.value)
        == "uq_moderation_actions_external_ref"
    )


async def test_deactivate_extra_active_bans_keeps_one_record(
    ban_db: str,
) -> None:
    """The cleanup helper revokes the duplicates and keeps the canonical one."""
    await _insert_ban(42, "oldban0001")
    await _insert_ban(42, "newban0001")

    count = await bans_db.deactivate_extra_active_bans(42, "newban0001")

    assert count == 1
    active = await bans_db.get_active_ban(42)
    assert active is not None
    assert active.get("ban_id") == "newban0001"
    assert await bans_db.user_ban_count(42) == 2


async def test_deactivate_extra_active_bans_touches_only_that_user(
    ban_db: str,
) -> None:
    """A user without duplicates keeps its single active ban."""
    await _insert_ban(42, "oldban0001")
    await _insert_ban(42, "newban0001")
    await _insert_ban(43, "onlyban001")

    count = await bans_db.deactivate_extra_active_bans(42, "newban0001")

    assert count == 1
    other = await bans_db.get_active_ban(43)
    assert other is not None
    assert other.get("ban_id") == "onlyban001"


async def test_the_canonical_record_is_the_active_one(ban_db: str) -> None:
    """The active ban is the record the profile and the appeal link name."""
    await _insert_ban(42, "oldban0001", active=False)
    await _insert_ban(42, "newban0001")

    active = await bans_db.get_active_ban(42)

    assert active is not None
    assert active.get("ban_id") == "newban0001"
