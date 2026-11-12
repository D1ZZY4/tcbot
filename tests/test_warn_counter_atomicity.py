# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter and history must agree, verified against a real PostgreSQL server.

The counter is what the auto-ban threshold reads, so it has to track the
warning history exactly. The history row and the counter share one
transaction, the decrement only runs when its delete removed a row, and
a clear removes both sides together.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot.database import engine as engine_module
from tcbot.database import warns_db
from tcbot.database.base import warn_counts, warns

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def warn_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from empty warning and counter tables."""
    await engine_module.run(warns.delete())
    await engine_module.run(warn_counts.delete())
    yield postgres_db
    await engine_module.run(warns.delete())
    await engine_module.run(warn_counts.delete())


async def _history_count(user_id: int, chat_id: int) -> int:
    """Return the number of stored warning rows for one user and chat."""
    return await engine_module.count_rows(
        warns.select().where(
            warns.c.user_id == user_id,
            warns.c.chat_id == chat_id,
        )
    )


async def _counter(user_id: int, chat_id: int) -> int:
    """Return the stored counter row for one user and chat."""
    row = await engine_module.fetch_one(
        warn_counts.select().where(
            warn_counts.c.user_id == user_id,
            warn_counts.c.chat_id == chat_id,
        )
    )
    if row is None:
        return 0
    return int(row["count"] or 0)


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


async def test_a_missing_counter_adopts_the_history_count(warn_db: str) -> None:
    """A warning must count the rows the history already holds.

    The counter row can be missing while the history is not, for example
    after a clear that failed between its two deletes. A counter that
    started at one would then sit below the history, and the auto-ban
    threshold would fire a warning late.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)
    await engine_module.run(warn_counts.delete())

    count = await warns_db.add_warn(42, "spam", 1, 5)

    assert count == 3
    assert await _history_count(42, 5) == 3
    assert await _counter(42, 5) == 3


async def test_concurrent_removals_keep_the_counter_and_the_history_aligned(
    warn_db: str,
) -> None:
    """Parallel removals must not decrement the counter twice.

    Two callers that read the same newest warning both try to remove it.
    Only one delete removes a row, so only one decrement may run, or the
    counter ends up below the history and the threshold fires late.
    """
    for _ in range(4):
        await warns_db.add_warn(42, "spam", 1, 5)

    await asyncio.gather(
        *(warns_db.remove_last_warn(42, 5) for _ in range(4)),
    )

    history = await _history_count(42, 5)
    counter = await _counter(42, 5)
    assert history == counter, f"history={history} counter={counter}"


async def test_a_removal_decrements_the_counter_once(warn_db: str) -> None:
    """One removal takes one warning off the history and the counter."""
    for _ in range(3):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.remove_last_warn(42, 5) is True

    assert await _history_count(42, 5) == 2
    assert await _counter(42, 5) == 2


async def test_a_removal_of_a_missing_warning_changes_nothing(warn_db: str) -> None:
    """Removing a warning that is gone reports it and leaves the count."""
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.remove_last_warn(42, 5) is True
    assert await warns_db.remove_last_warn(42, 5) is False

    assert await _history_count(42, 5) == 0
    assert await _counter(42, 5) == 0


async def test_a_failed_removal_leaves_the_counter_untouched(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed delete must not decrement the counter on its own.

    The delete and the decrement share one transaction, so a failing
    delete rolls the decrement back with it.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    _break_table_write(monkeypatch, warns, "the warns table is unavailable")

    with pytest.raises(RuntimeError, match="warns table is unavailable"):
        await warns_db.remove_last_warn(42, 5)

    assert await _history_count(42, 5) == 1
    assert await _counter(42, 5) == 1


async def test_a_clear_removes_the_history_and_the_counter(warn_db: str) -> None:
    """A clear takes both sides of the pair away."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.clear_warns(42, 5) == 2

    assert await _history_count(42, 5) == 0
    assert await _counter(42, 5) == 0


async def test_a_failed_clear_keeps_the_history(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed counter delete must not leave the history cleared.

    The two deletes share one transaction, so a failure rolls the history
    delete back with it. A surviving counter would otherwise keep a count
    for warnings that are gone and fire the threshold on a clean user.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    _break_table_write(monkeypatch, warn_counts, "the counter table is unavailable")

    with pytest.raises(RuntimeError, match="counter table is unavailable"):
        await warns_db.clear_warns(42, 5)

    assert await _history_count(42, 5) == 1
    assert await _counter(42, 5) == 1


async def test_a_removal_beside_a_repair_keeps_the_two_in_step(warn_db: str) -> None:
    """A removal and a repair that run together must not deadlock.

    The removal locks the warning row and then the counter row. The
    repair locks the counter row and then reads the history, so the two
    orders look inverted. The repair only reads, and a read takes no row
    lock, so there is no cycle. A change that made the repair lock the
    history rows would introduce one, so the property is pinned here.
    """
    for _ in range(3):
        await warns_db.add_warn(42, "spam", 1, 5)

    results = await asyncio.wait_for(
        asyncio.gather(
            warns_db.remove_last_warn(42, 5),
            warns_db._recount_and_store(42, 5),
            warns_db.remove_last_warn(42, 5),
            return_exceptions=True,
        ),
        timeout=20,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, failures

    history = await _history_count(42, 5)
    counter = await _counter(42, 5)
    assert history == counter, f"history={history} counter={counter}"
