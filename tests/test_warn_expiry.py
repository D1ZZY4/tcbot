# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warning expiry: the deadline belongs to the decision.

The community schema treats the expiry of a moderation decision as a fact
of it, so a warning carries its deadline from the moment it is filed and
the sweep never rewrites it. A warning that ran out stops counting
towards the threshold without its history being touched.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from tcbot import cfg
from tcbot.database import engine as engine_module
from tcbot.database import scheduler as jobs
from tcbot.database import warns_db
from tcbot.database.base import moderation_actions, moderation_cases
from tcbot.utils.time_and_date import utc_now
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def warn_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community."""
    await reset_community()
    await seed_users(1, 42)
    await seed_chats(5, cfg.proofs[0])
    yield postgres_db
    await reset_community()


def _lifetime(monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    """Set the configured warning lifetime for the test."""
    monkeypatch.setattr(
        warns_db,
        "cfg",
        dataclasses.replace(cfg, warn_expiry_days=days),
    )


async def _stored_warning() -> dict[str, Any] | None:
    """Return the single stored warning decision."""
    return await engine_module.fetch_one(
        moderation_actions.select().where(moderation_actions.c.action_type == "warn")
    )


async def _open_case(target_user_id: int, actor_user_id: int) -> int:
    """Open a case for the subject, so a decision has one to point at."""
    rows = await engine_module.run_returning(
        moderation_cases.insert()
        .values(
            subject_user_id=target_user_id,
            case_type="rule_violation",
            title=f"Case for {target_user_id}",
            status="open",
            source="manual",
            opened_by_user_id=actor_user_id,
            requires_evidence=False,
        )
        .returning(moderation_cases.c.id)
    )
    return int(rows[0]["id"])


async def test_a_warning_carries_its_deadline(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lifetime is part of the decision, not a later patch."""
    _lifetime(monkeypatch, 7)

    await warns_db.add_warn(42, "spam", 1, 5)

    stored = await _stored_warning()
    assert stored is not None
    assert stored["expires_at"] is not None
    assert stored["expires_at"] == stored["created_at"] + timedelta(days=7)


async def test_a_warning_without_a_lifetime_never_expires(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disabled lifetime leaves the warning without a deadline."""
    _lifetime(monkeypatch, 0)

    await warns_db.add_warn(42, "spam", 1, 5)

    stored = await _stored_warning()
    assert stored is not None
    assert stored["expires_at"] is None


async def test_a_warning_that_ran_out_stops_counting(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counter reads the expiry, so an old warning stops counting."""
    _lifetime(monkeypatch, 7)
    case_id = await _open_case(42, 1)
    created = utc_now() - timedelta(days=30)
    await engine_module.run(
        moderation_actions.insert().values(
            action_type="warn",
            scope_type="chat",
            chat_id=5,
            origin_chat_id=5,
            target_user_id=42,
            actor_user_id=1,
            reason="spam",
            created_at=created,
            expires_at=created + timedelta(seconds=1),
            status="completed",
            case_id=case_id,
            action_origin="manual",
        )
    )

    # * The decision keeps its facts and its row: only the counter moves,
    # * because it reads the expiry at query time.
    assert await warns_db.warn_count(42, 5) == 0
    stored = await _stored_warning()
    assert stored is not None
    assert stored["status"] == "completed"


async def test_the_sweep_leaves_a_warning_alone(warn_db: str) -> None:
    """The sweep expires the decisions that ran out, not the warnings.

    A warning keeps its ``completed`` status: the counter reads the
    expiry, so there is nothing for the sweep to rewrite.
    """
    await warns_db.add_warn(42, "spam", 1, 5)

    await jobs.expire_due_decisions()

    stored = await _stored_warning()
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["expires_at"] is None


async def test_the_sweep_expires_a_due_ban(warn_db: str) -> None:
    """A ban that ran out is expired and its revoke run is queued."""
    case_id = await _open_case(42, 1)
    created = utc_now() - timedelta(days=30)
    await engine_module.run(
        moderation_actions.insert().values(
            action_type="ban",
            scope_type="community",
            chat_id=None,
            target_user_id=42,
            actor_user_id=1,
            reason="spam",
            created_at=created,
            expires_at=created + timedelta(seconds=1),
            status="active",
            case_id=case_id,
            action_origin="automated",
        )
    )

    await jobs.expire_due_decisions()

    stored = await engine_module.fetch_one(
        moderation_actions.select().where(
            moderation_actions.c.action_type == "ban",
            moderation_actions.c.target_user_id == 42,
        )
    )
    assert stored is not None
    assert stored["status"] == "expired"
