# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter consistency verified against a real PostgreSQL server.

The warning history row and the running counter must agree: the counter
is what the auto-ban threshold reads, so a history row without its
counter would silently delay the ban the warning earned. Both writes
therefore share one transaction, and the counter upsert settles the
concurrent-first-warn race inside the database.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import pytest

from tcbot.database import engine as engine_module
from tcbot.database import warns_db
from tcbot.database.base import warn_counts, warns

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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


def _break_counter_insert(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Make the counter write fail, so the history write must roll back."""
    real_insert = warns_db.pg_insert

    def _failing_insert(table: Any, *args: Any, **kwargs: Any) -> Any:
        if table is warn_counts:
            raise error
        return real_insert(table, *args, **kwargs)

    monkeypatch.setattr(warns_db, "pg_insert", _failing_insert)


async def test_a_warning_raises_the_counter(warn_db: str) -> None:
    """The first warning stores one history row and a counter of one."""
    count = await warns_db.add_warn(42, "spam", 1, 5)

    assert count == 1
    assert await _history_count(42, 5) == 1
    assert await warns_db.warn_count(42, 5) == 1


async def test_concurrent_warnings_keep_every_increment(warn_db: str) -> None:
    """Parallel warnings must not lose a counter increment.

    The counter row is the count, and the primary key on
    ``(user_id, chat_id)`` makes two concurrent first-warnings collide on
    the insert. The conflict clause folds the increment into the stored
    row, so no increment disappears.
    """
    await asyncio.gather(
        *(warns_db.add_warn(42, "spam", 1, 5) for _ in range(5)),
    )

    assert await _history_count(42, 5) == 5
    assert await warns_db.warn_count(42, 5) == 5


async def test_a_failed_counter_leaves_no_orphan_history(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken counter must not leave a warning row behind.

    The history row and the counter share one transaction, so a failing
    counter rolls the history row back with it. A half-written warning
    would count against the user without raising their counter.
    """
    _break_counter_insert(monkeypatch, RuntimeError("counter is unavailable"))

    with pytest.raises(RuntimeError, match="counter is unavailable"):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await _history_count(42, 5) == 0
    assert await warns_db.warn_count(42, 5) == 0


async def test_the_backfill_uses_the_stored_count_when_present(warn_db: str) -> None:
    """A counter row that exists is trusted instead of recomputed."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    assert await warns_db.warn_count(42, 5) == 2


async def test_the_backfill_reconstructs_a_missing_counter(warn_db: str) -> None:
    """A missing counter row is rebuilt from the warning history."""
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)
    await engine_module.run(warn_counts.delete())

    assert await warns_db.warn_count(42, 5) == 2


async def test_cancellation_propagates(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled warning never commits a half-written pair."""
    _break_counter_insert(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await warns_db.add_warn(42, "spam", 1, 5)

    assert await _history_count(42, 5) == 0


class _Gate:
    """One-shot gate that holds the first counter write until released."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self._claimed = False

    def claim(self) -> bool:
        """Take the gate, so only the first counter write waits on it."""
        if self._claimed:
            return False
        self._claimed = True
        return True

    async def wait(self) -> None:
        """Stop the claimed statement until the gate is released."""
        self.reached.set()
        await self.release.wait()


def _writes_the_counter(stmt: Any) -> bool:
    """Return True when the statement writes the warn counter table."""
    return getattr(stmt, "table", None) is warn_counts


class _PausingSession:
    """Session proxy that holds the first counter write until released."""

    def __init__(self, sess: Any, gate: _Gate) -> None:
        self._sess = sess
        self._gate = gate

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        """Hold the first counter write, then run the statement."""
        if _writes_the_counter(stmt) and self._gate.claim():
            await self._gate.wait()
        return await self._sess.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the real session."""
        return getattr(self._sess, name)


def _pause_the_first_counter_write(
    monkeypatch: pytest.MonkeyPatch, gate: _Gate
) -> None:
    """Hold the first statement that writes the counter table."""
    real_session = engine_module.session
    real_read = engine_module.read_connection

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[Any]:
        async with real_session() as sess:
            yield _PausingSession(sess, gate)

    @contextlib.asynccontextmanager
    async def _read() -> AsyncIterator[Any]:
        async with real_read() as conn:
            yield _PausingSession(conn, gate)

    monkeypatch.setattr(engine_module, "session", _session)
    monkeypatch.setattr(engine_module, "read_connection", _read)


async def test_a_concurrent_warning_survives_a_counter_repair(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repair that runs beside a warning must not drop that warning.

    The repair recounts the history and stores the absolute count, so it
    has to hold the counter row while it counts. A repair that read the
    history in one statement and wrote the count in another would let the
    concurrent warning land in between, and the repair would overwrite
    its increment: the counter would sit one below the history and the
    automatic ban would fire one warning late.
    """
    await warns_db.add_warn(42, "spam", 1, 5)
    await warns_db.add_warn(42, "spam", 1, 5)

    gate = _Gate()
    _pause_the_first_counter_write(monkeypatch, gate)

    repair = asyncio.create_task(warns_db._recount_and_store(42, 5))
    await asyncio.wait_for(gate.reached.wait(), timeout=5)

    # * The concurrent warning starts while the repair sits on its counter
    # * write. It must not be awaited yet: a repair that holds the counter
    # * row makes the warning wait for it.
    concurrent = asyncio.create_task(warns_db.add_warn(42, "spam", 1, 5))
    await asyncio.sleep(0.05)
    gate.release.set()

    await repair
    await concurrent

    assert await _history_count(42, 5) == 3
    assert await warns_db.warn_count(42, 5) == 3
    assert await warns_db.federation_warn_count(42) == 3
