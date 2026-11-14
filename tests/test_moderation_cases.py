# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The lifecycle of a moderation case against a real PostgreSQL server.

A case is the investigation that holds a decision. It opens with the
decision and closes with it, so every incident owns one case and the
next decision about the same user starts a new investigation. The checks
here run against the schema, because the triggers that enforce the
lifecycle live there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from tcbot import cfg
from tcbot.database import bans_db, warns_db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_cases
from tests.postgres_support import (
    reset_community,
    seed_case,
    seed_chats,
    seed_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def community_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community with one group and one proof channel."""
    await reset_community()
    await seed_users(1, 7, 42)
    await seed_chats(-1001, cfg.proofs[0])
    yield postgres_db
    await reset_community()


async def _case_of(action_id: int) -> dict[str, object]:
    """Return the case row of one decision."""
    row = await engine_module.fetch_one(
        select(
            moderation_cases.c.id,
            moderation_cases.c.status,
            moderation_cases.c.requires_evidence,
            moderation_cases.c.closed_by_user_id,
        )
        .join(
            moderation_actions,
            moderation_actions.c.case_id == moderation_cases.c.id,
        )
        .where(moderation_actions.c.id == action_id)
    )
    assert row is not None
    return row


async def _cases_of(target_user_id: int) -> list[dict[str, object]]:
    """Return every case of one user, oldest first."""
    return await engine_module.fetch_all(
        select(
            moderation_cases.c.id,
            moderation_cases.c.status,
            moderation_cases.c.requires_evidence,
        )
        .where(moderation_cases.c.subject_user_id == target_user_id)
        .order_by(moderation_cases.c.id)
    )


async def test_a_filed_decision_closes_its_case(community_db: str) -> None:
    """The investigation ends with the decision it belongs to."""
    await warns_db.add_warn(42, "spam", 7, -1001)

    action = await engine_module.fetch_one(
        select(moderation_actions.c.id, moderation_actions.c.case_id).where(
            moderation_actions.c.target_user_id == 42
        )
    )
    assert action is not None
    case = await _case_of(int(action["id"]))

    assert case["status"] == "resolved"
    assert case["closed_by_user_id"] == 7


async def test_every_decision_owns_its_own_case(community_db: str) -> None:
    """Two warnings about one user are two investigations."""
    await warns_db.add_warn(42, "spam", 7, -1001)
    await warns_db.add_warn(42, "spam again", 7, -1001)

    cases = await _cases_of(42)

    assert len(cases) == 2
    assert all(case["status"] == "resolved" for case in cases)


async def test_an_automated_decision_ignores_a_pending_evidence_case(
    community_db: str,
) -> None:
    """A threshold ban is not blocked by an unrelated open investigation.

    An open case that demands evidence belongs to an investigation that
    is still gathering proof. A decision that may stand on its own must
    not inherit that requirement: the database refuses a ban that
    promises proof it does not carry, and the threshold ban would fail
    instead of being filed.
    """
    await seed_case(42, opened_by_user_id=7, requires_evidence=True)

    ban = await bans_db.create_ban(
        42, "spam", 7, 0, 0, "autoban0001", action_origin="automated"
    )

    assert ban.get("ban_id") == "autoban0001"
    cases = await _cases_of(42)
    assert len(cases) == 2
    automated = next(case for case in cases if case["requires_evidence"] is False)
    assert automated["status"] == "resolved"


async def test_a_reban_opens_a_new_case_and_supersedes_the_old_decision(
    community_db: str,
) -> None:
    """A re-ban is a new incident with its own case."""
    first = await bans_db.create_ban(42, "spam", 7, 501, 0, "firstban001")

    second = await bans_db.update_ban(
        str(first.get("ban_id", "")), "spam again", 7, 502, 0, 501, 0
    )

    assert second is not None
    assert second.get("ban_id") != first.get("ban_id")
    cases = await _cases_of(42)
    assert len(cases) == 2
    old_case = await _case_of(int(first.get("id", 0)))
    new_case = await _case_of(int(second.get("id", 0)))
    assert old_case["id"] != new_case["id"]
    superseded = await engine_module.fetch_one(
        select(moderation_actions.c.status).where(
            moderation_actions.c.id == int(first.get("id", 0))
        )
    )
    assert superseded is not None
    assert superseded["status"] == "superseded"
