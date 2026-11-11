# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""set_owner: the transfer is atomic, fails closed, and keeps one owner."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.sql.expression import Delete

from tcbot.database import engine as engine_module
from tcbot.database import users_roles
from tcbot.database.base import tc_owners
from tcbot.database.cache import _OWNER_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def owner_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty owner table."""
    await engine_module.run(tc_owners.delete())
    yield postgres_db
    await engine_module.run(tc_owners.delete())


class _FailingDeleteSession:
    """Session proxy that rejects the cleanup delete."""

    def __init__(self, sess: AsyncSession) -> None:
        self._sess = sess

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        """Fail the cleanup delete, pass everything else through."""
        if isinstance(stmt, Delete):
            raise RuntimeError("tc_owners delete failed")
        return await self._sess.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the real session."""
        return getattr(self._sess, name)


def _install_failing_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the cleanup delete fail inside the transfer transaction."""
    real_session = engine_module.session

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[_FailingDeleteSession]:
        async with real_session() as sess:
            yield _FailingDeleteSession(sess)

    monkeypatch.setattr(engine_module, "session", _session)


async def _owner_ids() -> list[int]:
    """Return every owner row, ordered."""
    rows = await engine_module.fetch_all(tc_owners.select())
    return [int(row["user_id"]) for row in rows]


async def test_set_owner_leaves_exactly_one_owner(owner_db: str) -> None:
    """A successful transfer replaces the owner instead of adding one."""
    await users_roles.set_owner(61001)
    try:
        await users_roles.set_owner(61002)
        assert await _owner_ids() == [61002]
    finally:
        users_roles.owner_id_cache.invalidate(_OWNER_KEY)


async def test_a_failed_transfer_keeps_the_previous_owner(
    owner_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rolled-back transfer must not leave the table without an owner.

    The insert and the cleanup delete share one transaction, so a failure
    between them cannot leave zero owner rows. Zero owners would leave the
    whole federation without a Founder until the next restart.
    """
    await users_roles.set_owner(61003)
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)
    _install_failing_delete(monkeypatch)

    with pytest.raises(RuntimeError, match="tc_owners delete failed"):
        await users_roles.set_owner(61004)

    assert await _owner_ids() == [61003]
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)


async def test_set_owner_persistent_delete_failure_reraises_with_guidance(
    owner_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed transfer fails closed and points the operator at the table."""
    _install_failing_delete(monkeypatch)
    with (
        caplog.at_level(logging.ERROR, logger="tcbot.database.users_roles"),
        pytest.raises(RuntimeError, match="tc_owners delete failed"),
    ):
        await users_roles.set_owner(61010)

    assert "tc_owners" in caplog.text
    assert "rolled back" in caplog.text


async def test_set_owner_delete_cancellation_propagates(
    owner_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled transfer must propagate and leave the owner untouched."""
    real_session = engine_module.session

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[Any]:
        async with real_session() as sess:
            raise asyncio.CancelledError()
            yield sess  # pragma: no cover - unreachable, keeps the shape typed

    monkeypatch.setattr(engine_module, "session", _session)

    with pytest.raises(asyncio.CancelledError):
        await users_roles.set_owner(61011)

    assert await _owner_ids() == []


async def test_concurrent_transfers_leave_exactly_one_owner(owner_db: str) -> None:
    """Two transfers racing must not cancel each other out.

    The transfer takes an advisory lock, so the losers wait instead of
    interleaving their insert and delete. Without the lock the sequence
    insert A, insert B, delete != A, delete != B leaves no owner row.
    """
    await asyncio.gather(
        users_roles.set_owner(61100),
        users_roles.set_owner(61200),
        users_roles.set_owner(61300),
    )
    try:
        assert len(await _owner_ids()) == 1
    finally:
        users_roles.owner_id_cache.invalidate(_OWNER_KEY)
