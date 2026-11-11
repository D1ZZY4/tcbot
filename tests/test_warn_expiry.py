# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn expiry: the prune is atomic and a failure surfaces as a job failure."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.sql.expression import Delete

from tcbot.database import engine as engine_module
from tcbot.database import scheduler as jobs
from tcbot.database.base import warn_counts, warns

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def warn_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from empty warning and counter tables."""
    await engine_module.run(warns.delete())
    await engine_module.run(warn_counts.delete())
    yield postgres_db
    await engine_module.run(warns.delete())
    await engine_module.run(warn_counts.delete())


class _FailingCountsSession:
    """Session proxy that rejects the ``warn_counts`` delete."""

    def __init__(self, sess: AsyncSession) -> None:
        self._sess = sess

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        """Fail the counter delete, pass everything else through."""
        if isinstance(stmt, Delete) and stmt.table is warn_counts:
            raise RuntimeError("delete failed")
        return await self._sess.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the real session."""
        return getattr(self._sess, name)


def _break_counter_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the counter delete fail inside the expiry transaction."""
    real_session = engine_module.session

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[_FailingCountsSession]:
        async with real_session() as sess:
            yield _FailingCountsSession(sess)

    monkeypatch.setattr(engine_module, "session", _session)


async def test_expire_success_does_not_raise(warn_db: str) -> None:
    """A clean expiry run reports success."""
    await jobs.expire_old_warns(7)


async def test_expire_partial_failure_raises(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-finished expiry must fail the run, not report success."""
    _break_counter_delete(monkeypatch)

    with pytest.raises(RuntimeError, match="rolled back"):
        await jobs.expire_old_warns(7)


async def test_a_failed_expiry_leaves_both_tables_untouched(
    warn_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two deletes share a transaction, so one failure prunes neither.

    Pruning only the counters would let the counter backfill rebuild them
    from the surviving history, and pruning only the history would leave a
    counter that counts a warning nobody can see. Both outcomes would make
    the auto-ban threshold fire on a warning that is gone.
    """
    await engine_module.run(
        warns.insert().values(user_id=42, chat_id=5, reason="spam", admin_id=1)
    )
    await engine_module.run(warn_counts.insert().values(user_id=42, chat_id=5, count=1))
    _break_counter_delete(monkeypatch)

    with pytest.raises(RuntimeError):
        await jobs.expire_old_warns(7)

    assert await engine_module.count_rows(warns.select()) == 1
    assert await engine_module.count_rows(warn_counts.select()) == 1


async def test_expire_is_a_no_op_when_disabled(warn_db: str) -> None:
    """A non-positive expiry window must never delete anything."""
    await engine_module.run(
        warns.insert().values(user_id=42, chat_id=5, reason="spam", admin_id=1)
    )

    await jobs.expire_old_warns(0)

    assert await engine_module.count_rows(warns.select()) == 1
