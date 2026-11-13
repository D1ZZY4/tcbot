# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""End-to-end exercise of the data layer on a real PostgreSQL server.

The test server is the production backend: the schema is built from the
declared metadata, the community objects are applied from the schema
package, and the migrated helpers read and write through the shared
engine, exactly like the running bot does. The tests skip when no server
is configured, so the committed suite never depends on one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot import cfg
from tcbot.database import bans_db, groups_db, users_cache, warns_db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_cases
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# * Every test in this module needs a real PostgreSQL server.
pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def postgres(postgres_db: str) -> AsyncIterator[str]:
    """Point the shared engine at the test server with an empty community."""
    await reset_community()
    await seed_users(7, 9, 42)
    await seed_chats(-1001, -1002, cfg.proofs[0])
    yield postgres_db
    await reset_community()


async def test_a_ban_is_written_and_read_back(postgres: str) -> None:
    """A created ban comes back with the fields the moderator entered."""
    created = await bans_db.create_ban(42, "spam", 7, 11, 12)
    ban_id = str(created.get("ban_id"))

    stored = await bans_db.get_ban(ban_id)
    assert stored is not None
    assert stored.get("banned_user_id") == 42
    assert stored.get("reason") == "spam"
    assert stored.get("admin_user_id") == 7
    assert stored.get("proof_message_id") == 11
    assert stored.get("log_message_id") == 12
    assert stored.get("is_active") is True

    active = await bans_db.get_active_ban(42)
    assert active is not None
    assert str(active.get("ban_id")) == ban_id
    assert await bans_db.active_ban_count() == 1


async def test_the_database_refuses_a_second_active_ban(postgres: str) -> None:
    """One active ban per user, enforced by the database."""
    await bans_db.create_ban(42, "spam", 7, 11, 12)

    # * The second decision is filed under a case that does not require
    # * evidence, so the proof guard does not reject it first: the unique
    # * index is the constraint under test.
    await engine_module.run(
        pg_insert(moderation_cases).values(
            subject_user_id=42,
            title="Second ban",
            status="open",
            source="manual",
            opened_by_user_id=7,
            requires_evidence=False,
        )
    )
    case = await engine_module.fetch_one(
        moderation_cases.select().where(moderation_cases.c.title == "Second ban")
    )
    assert case is not None

    with pytest.raises(IntegrityError) as excinfo:
        await engine_module.run(
            pg_insert(moderation_actions).values(
                action_type="ban",
                scope_type="community",
                target_user_id=42,
                actor_user_id=7,
                reason="spam",
                status="active",
                case_id=case["id"],
                action_origin="automated",
                external_ref="secondban1",
            )
        )

    assert (
        engine_module.constraint_name(excinfo.value)
        == "uq_moderation_actions_active_ban"
    )


async def test_the_warn_counter_increments(postgres: str) -> None:
    """Every warn raises the counter of the user in that group."""
    first = await warns_db.add_warn(42, "spam", 7, -1001)
    second = await warns_db.add_warn(42, "spam", 7, -1001)

    assert first == 1
    assert second == 2
    assert await warns_db.warn_count(42, -1001) == 2
    stored = await engine_module.fetch_one(
        text("SELECT chat_id, user_id, count FROM warn_counts WHERE chat_id = -1001")
    )
    assert stored is not None
    assert int(stored["count"]) == 2


async def test_the_group_locale_round_trips(postgres: str) -> None:
    """A group locale is stored, read back and cleared again."""
    await groups_db.add_group(-1001, "Test Group", 7)

    assert await groups_db.set_group_locale(-1001, "id-ID") is True
    assert await groups_db.get_group_locale(-1001) == "id-ID"

    assert await groups_db.set_group_locale(-1001, None) is True
    assert await groups_db.get_group_locale(-1001) is None


async def test_the_member_cache_name_search_finds_the_user(postgres: str) -> None:
    """A profile written through the cache is found by the prefix search."""
    await users_cache.upsert_user(7, "Alice_1", "Alice", "Smith")

    found = await users_cache.search_by_name("ali")

    assert [doc.get("user_id") for doc in found] == [7]
    assert found[0].get("first_name") == "Alice"
    assert found[0].get("username") == "Alice_1"


async def test_the_migrated_helpers_share_one_transaction_boundary(
    postgres: str,
) -> None:
    """The helpers read what the previous helper wrote, through one engine."""
    await users_cache.upsert_user(9, "Carol", "Carol")
    await warns_db.add_warn(9, "spam", 7, -1002)

    stored = await users_cache.get_user(9)
    counter = await warns_db.warn_count(9, -1002)

    assert stored is not None
    assert stored.get("first_name") == "Carol"
    assert counter == 1


def test_the_module_is_marked() -> None:
    """The module carries the postgres marker the CI selects on."""
    assert any(mark.name == "postgres" for mark in pytestmark)
