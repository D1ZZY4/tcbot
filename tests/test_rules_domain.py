# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules domain persistence: lifecycle, run lock, acknowledgement, case links."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from tcbot import database as db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_case_rules, rule_set_versions
from tcbot.database.engine import fetch_all, fetch_one, run_transaction
from tcbot.database.rules_db import runs as runs_db
from tests.postgres_support import (
    SCHEMA_TABLES,
    _toggle_guards,
    reset_community,
    seed_case,
    seed_chats,
    seed_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

_RULE_TABLES = (
    "rule_acknowledgements",
    "moderation_case_rules",
    "rule_publications",
    "rule_publication_runs",
    "rule_items",
    "rule_set_versions",
    "rule_categories",
    "rule_sets",
)


def _clear_rules_script() -> str:
    """Empty the rules tables with the append-only guards temporarily off."""
    assert SCHEMA_TABLES
    return (
        f"{_toggle_guards('DISABLE')};\n"
        f"TRUNCATE {', '.join(_RULE_TABLES)} CASCADE;\n"
        f"{_toggle_guards('ENABLE')};\n"
    )


@pytest.fixture
async def rules_ready(postgres_db: str) -> AsyncIterator[str]:
    """Start each case with an empty rules domain."""
    await reset_community()
    await engine_module.run_script(_clear_rules_script())
    yield postgres_db
    await engine_module.run_script(_clear_rules_script())
    await reset_community()


async def test_a_new_draft_publishes_and_supersedes_the_previous_version(
    rules_ready: str,
) -> None:
    await seed_users(7, 8)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])

    first_draft = await db.rules_db.open_draft(set_id, 7)
    await db.rules_db.add_item(first_draft["id"], "conduct", "No spam", "Do not spam")
    await db.rules_db.promote_version(first_draft["id"], 7)

    first_published = await db.rules_db.published_version(set_id)
    assert first_published is not None
    assert int(first_published["id"]) == int(first_draft["id"])

    second_draft = await db.rules_db.open_draft(set_id, 8)
    await db.rules_db.add_item(second_draft["id"], "conduct", "Be kind", "Be kind")
    await db.rules_db.promote_version(second_draft["id"], 8)

    second_published = await db.rules_db.published_version(set_id)
    assert second_published is not None
    assert int(second_published["id"]) == int(second_draft["id"])

    old = await fetch_one(
        select(rule_set_versions).where(
            rule_set_versions.c.id == int(first_draft["id"])
        )
    )
    assert old is not None
    assert old["status"] == "superseded"
    assert len(await db.rules_db.all_items(int(first_draft["id"]))) == 1


async def test_only_one_publication_run_is_live_per_set_and_channel(
    rules_ready: str,
) -> None:
    await seed_users(7)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    draft = await db.rules_db.open_draft(set_id, 7)

    run_id = await runs_db.acquire(set_id, int(draft["id"]), -100123)
    with pytest.raises(RuntimeError, match="already running"):
        await runs_db.acquire(set_id, int(draft["id"]), -100123)

    active = await runs_db.active(set_id, -100123)
    assert active is not None
    assert int(active["id"]) == run_id

    await runs_db.finish(run_id, "completed")
    assert await runs_db.active(set_id, -100123) is None


async def test_an_expired_publication_run_is_reclaimed(rules_ready: str) -> None:
    await seed_users(7)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    draft = await db.rules_db.open_draft(set_id, 7)

    await runs_db.acquire(set_id, int(draft["id"]), -100123, lease=-1)
    reclaimed = await runs_db.reclaim_expired()

    assert reclaimed == 1
    assert await runs_db.active(set_id, -100123) is None
    # * The failed run frees the slot for a fresh publish.
    assert await runs_db.acquire(set_id, int(draft["id"]), -100123) > 0


async def test_acknowledgement_is_idempotent_and_counted(rules_ready: str) -> None:
    await seed_users(7)
    await seed_chats(-1001)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    draft = await db.rules_db.open_draft(set_id, 7)
    await db.rules_db.add_item(draft["id"], "conduct", "Rule", "Body")
    await db.rules_db.promote_version(draft["id"], 7)
    published = await db.rules_db.published_version(set_id)
    assert published is not None
    version_id = int(published["id"])

    assert await db.rules_db.record_acknowledgement(version_id, 7, -1001, 55) is True
    assert await db.rules_db.has_acknowledged(version_id, 7) is True
    assert await db.rules_db.acknowledgement_count(version_id) == 1

    # * A repeated tap must not double-count the same member.
    assert await db.rules_db.record_acknowledgement(version_id, 7, -1001, 55) is False
    assert await db.rules_db.acknowledgement_count(version_id) == 1


async def test_selected_rules_link_to_the_decision_case(rules_ready: str) -> None:
    await seed_users(7, 9)
    await seed_chats(-1001)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    draft = await db.rules_db.open_draft(set_id, 7)
    item = await db.rules_db.add_item(draft["id"], "conduct", "No spam", "Body")
    await db.rules_db.promote_version(draft["id"], 7)
    case_id = await seed_case(9, opened_by_user_id=7)

    async def _work(sess: AsyncSession) -> None:
        await db.moderation_db.link_case_rules(
            sess, case_id, [int(item["id"])], 7, -1001
        )

    await run_transaction(_work)

    links = await fetch_all(
        select(moderation_case_rules).where(moderation_case_rules.c.case_id == case_id)
    )
    assert len(links) == 1
    assert int(links[0]["rule_item_id"]) == int(item["id"])
    assert links[0]["attribution_source"] == "moderator"
