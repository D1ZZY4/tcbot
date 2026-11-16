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

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from tcbot import cfg
from tcbot.database import bans_db, warns_db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_cases, telegram_users
from tcbot.utils.time_and_date import utc_now
from tests.postgres_support import (
    reset_community,
    seed_action,
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


async def test_a_decision_files_for_an_uncached_target(postgres_db: str) -> None:
    """A decision creates the identity rows its foreign keys reference.

    The member cache only learns a user from an observed update, so a
    moderator acting on an account the bot has never seen used to fail the
    decision on a foreign key. The target row is created with the decision.
    """
    await reset_community()
    try:
        await seed_users(7)
        await seed_chats(-1001, cfg.proofs[0])

        await warns_db.add_warn(42, "spam", 7, -1001)

        row = await engine_module.fetch_one(
            select(telegram_users.c.user_id).where(telegram_users.c.user_id == 42)
        )
        assert row == {"user_id": 42}
    finally:
        await reset_community()


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


async def test_a_reban_of_a_superseded_decision_supersedes_the_current_ban(
    community_db: str,
) -> None:
    """An older reference still lands the decision on the live ban.

    A proof window can stay open while another moderator re-bans the same
    target, so the record a flow read at entry is already superseded when
    it writes. The new decision must supersede the ban that is active at
    write time instead of failing the supersession rule.
    """
    first = await bans_db.create_ban(42, "spam", 7, 501, 0, "firstban001")
    second = await bans_db.update_ban(
        str(first.get("ban_id", "")), "spam again", 7, 502, 0, 501, 0
    )
    assert second is not None

    third = await bans_db.update_ban(
        str(first.get("ban_id", "")), "spam once more", 8, 503, 0, 501, 0
    )

    assert third is not None
    assert third.get("ban_id") not in (first.get("ban_id"), second.get("ban_id"))
    active = await bans_db.get_active_ban(42)
    assert active is not None
    assert active.get("ban_id") == third.get("ban_id")
    cases = await _cases_of(42)
    assert len(cases) == 3
    assert all(case["status"] == "resolved" for case in cases)


async def test_a_reban_of_an_elapsed_decision_starts_a_fresh_active_ban(
    community_db: str,
) -> None:
    """An elapsed record is expired by the insert, not named as superseded.

    A re-ban can reach the write after the previous ban passed its deadline
    during the proof window. The insert trigger expires that row before it
    resolves the supersession, so naming it would fail the rule. The new
    decision must stand on its own.
    """
    now = utc_now()
    await seed_action(
        "ban",
        42,
        actor_user_id=7,
        external_ref="expiredban01",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )

    fresh = await bans_db.update_ban("expiredban01", "spam again", 7, 503, 0, 0, 0)

    assert fresh is not None
    assert fresh.get("is_active") is True
    active = await bans_db.get_active_ban(42)
    assert active is not None
    assert active.get("ban_id") == fresh.get("ban_id")
    previous = await bans_db.get_ban("expiredban01")
    assert previous is not None
    assert previous.get("status") == "expired"
