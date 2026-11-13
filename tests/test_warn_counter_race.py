# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter consistency verified against a real PostgreSQL server.

The count the auto-ban threshold reads is a view over the warning
decisions, so it cannot fall behind them: every warning is a decision
row, and the view counts the rows that are still in force. The decision
and the case that holds it share one transaction, so a warning never
exists without its investigation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from tcbot import cfg
from tcbot.database import engine as engine_module
from tcbot.database import warns_db
from tcbot.database.base import moderation_actions, moderation_cases
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


async def _decision_count(user_id: int, chat_id: int) -> int:
    """Return the number of stored warning decisions for one user and chat."""
    return await engine_module.count_rows(
        moderation_actions.select().where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "warn",
            moderation_actions.c.chat_id == chat_id,
        )
    )


def _break_decision_insert(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Make the decision write fail, so the case write must roll back."""
    real_insert = warns_db.pg_insert

    def _failing_insert(table: Any, *args: Any, **kwargs: Any) -> Any:
        if table is moderation_actions:
            raise error
        return real_insert(table, *args, **kwargs)

    monkeypatch.setattr(warns_db, "pg_insert", _failing_insert)


async def test_a_warning_raises_the_counter(warn_db: str) -> None:
    """The first warning stores one decision and a count of one."""
    count = await warns_db.add_warn(42, "spam", 1, 5)

    assert count == 1
    assert await _decision_count(42, 5) == 1
    assert await warns_db.warn_count(42, 5) == 1


async def test_concurrent_warnings_keep_every_increment(warn_db: str) -> None:
    """Parallel warnings must not lose a warning.

    Every warning is its own decision row, so nothing has to fold an
    increment into a shared counter: the count follows the rows.
    """
    await asyncio.gather(
        *(warns_db.add_warn(42, "spam", 1, 5) for _ in range(5)),
    )

    assert await _decision_count(42, 5) == 5
    assert await warns_db.warn_count(42, 5) == 5


async def test_a_failed_decision_leaves_no_orphan_case(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken decision must not leave a case behind.

    The decision and the case share one transaction, so a failing write
    rolls the case back with it. A case without a warning would keep the
    investigation open for a decision that never happened.
    """
    _break_decision_insert(monkeypatch, RuntimeError("decisions are unavailable"))

    with pytest.raises(RuntimeError, match="decisions are unavailable"):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await _decision_count(42, 5) == 0
    assert await warns_db.warn_count(42, 5) == 0
    cases = await engine_module.count_rows(
        moderation_cases.select().where(
            moderation_cases.c.subject_user_id == 42,
        )
    )
    assert cases == 0


async def test_the_count_always_agrees_with_the_decisions(warn_db: str) -> None:
    """A count that exists is read from the decisions instead of recomputed."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.warn_count(42, 5) == 2


async def test_the_count_follows_a_removed_decision(warn_db: str) -> None:
    """A revoked warning leaves the count on its own."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    await warns_db.remove_last_warn(42, 5)

    assert await warns_db.warn_count(42, 5) == 1


async def test_cancellation_propagates(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled warning never commits a half-written decision."""
    _break_decision_insert(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await _decision_count(42, 5) == 0
