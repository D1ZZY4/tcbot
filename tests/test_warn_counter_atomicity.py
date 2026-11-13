# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter and history must agree, verified against a real PostgreSQL server.

The counter is what the auto-ban threshold reads, so it has to track the
warning history exactly. The counter is a view over the decisions, so it
cannot fall behind them: a revoked warning leaves the count on its own and
the history keeps the record.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot import cfg
from tcbot.database import engine as engine_module
from tcbot.database import warns_db
from tcbot.database.base import moderation_actions
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.postgres]


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


async def _live_count(user_id: int, chat_id: int) -> int:
    """Return the number of warning decisions that are still in force."""
    return await engine_module.count_rows(
        moderation_actions.select().where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "warn",
            moderation_actions.c.chat_id == chat_id,
            moderation_actions.c.status == "completed",
        )
    )


async def _counter(user_id: int, chat_id: int) -> int:
    """Return the counted warnings of one user in one chat."""
    return await warns_db.warn_count(user_id, chat_id)


def _break_table_write(
    monkeypatch: pytest.MonkeyPatch, table: Any, message: str
) -> None:
    """Make every write to *table* fail, so its transaction partner rolls back."""
    real_execute = AsyncSession.execute

    async def _failing_execute(self: Any, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(stmt, "table", None) is table:
            raise RuntimeError(message)
        return await real_execute(self, stmt, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", _failing_execute)


async def test_the_counter_follows_the_history(warn_db: str) -> None:
    """A warning must count the rows the history already holds.

    The counter is a view over the decisions, so it cannot sit below the
    history: the auto-ban threshold always reads the number of warnings
    that are really in force.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    count = await warns_db.add_warn(42, "spam", 1, 5)

    assert count == 3
    assert await _decision_count(42, 5) == 3
    assert await _counter(42, 5) == 3


async def test_concurrent_removals_keep_the_counter_and_the_history_aligned(
    warn_db: str,
) -> None:
    """Parallel removals must not revoke a warning twice.

    Two callers that read the same newest warning both try to remove it.
    Only one update moves the row out of the counted state, so the count
    and the history stay in step.
    """
    for _ in range(4):
        await warns_db.add_warn(42, "spam", 1, 5)

    await asyncio.gather(
        *(warns_db.remove_last_warn(42, 5) for _ in range(4)),
    )

    counter = await _counter(42, 5)
    live = await _live_count(42, 5)
    assert counter == live, f"counter={counter} live={live}"
    assert counter < 4, "a removal must take one warning out of the count"


async def test_a_removal_decrements_the_counter_once(warn_db: str) -> None:
    """One removal takes one warning off the count and keeps the record."""
    for _ in range(3):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.remove_last_warn(42, 5) is True

    assert await _counter(42, 5) == 2
    assert await _decision_count(42, 5) == 3


async def test_a_removal_of_a_missing_warning_changes_nothing(warn_db: str) -> None:
    """Removing a warning that is gone reports it and leaves the count."""
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.remove_last_warn(42, 5) is True
    assert await warns_db.remove_last_warn(42, 5) is False

    assert await _counter(42, 5) == 0
    assert await _decision_count(42, 5) == 1


async def test_a_failed_removal_leaves_the_counter_untouched(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed write must not move the warning out of the count.

    The decision and the count are one row, so a failing write leaves the
    counted state exactly as it was.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    _break_table_write(
        monkeypatch, moderation_actions, "the decisions table is unavailable"
    )

    with pytest.raises(RuntimeError, match="decisions table is unavailable"):
        await warns_db.remove_last_warn(42, 5)

    assert await _counter(42, 5) == 1


async def test_a_clear_revokes_the_warnings_and_keeps_the_history(
    warn_db: str,
) -> None:
    """A clear takes the warnings out of the count and keeps the record."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.clear_warns(42, 5) == 2

    assert await _counter(42, 5) == 0
    assert await _decision_count(42, 5) == 2


async def test_a_failed_clear_keeps_the_warnings(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed clear must not leave the warnings out of the count.

    The clear is one transaction, so a failure rolls the revocation back
    with it. A count that lost its warnings while the decisions survived
    would fire the threshold on a user nobody warned.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    _break_table_write(
        monkeypatch, moderation_actions, "the decisions table is unavailable"
    )

    with pytest.raises(RuntimeError, match="decisions table is unavailable"):
        await warns_db.clear_warns(42, 5)

    assert await _counter(42, 5) == 1


async def test_parallel_removals_do_not_deadlock(warn_db: str) -> None:
    """Parallel removals must not lock each other out.

    The removal moves one decision out of the counted state, so two
    removals that read the same row race for it. The update is
    conditional, so one of them finds nothing left to move.
    """
    for _ in range(3):
        await warns_db.add_warn(42, "spam", 1, 5)

    results = await asyncio.wait_for(
        asyncio.gather(
            warns_db.remove_last_warn(42, 5),
            warns_db.remove_last_warn(42, 5),
            warns_db.remove_last_warn(42, 5),
            return_exceptions=True,
        ),
        timeout=20,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, failures

    counter = await _counter(42, 5)
    live = await _live_count(42, 5)
    assert counter == live, f"counter={counter} live={live}"
