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
from sqlalchemy.sql.expression import Update

from tcbot.database import engine as engine_module
from tcbot.database import users_roles
from tcbot.database.base import role_assignments
from tcbot.database.cache import _OWNER_KEY
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

# * The users the transfers in this module hand the ownership to.
_OWNER_IDS: tuple[int, ...] = (
    61001,
    61002,
    61003,
    61004,
    61010,
    61011,
    61100,
    61200,
    61300,
)


@pytest.fixture
async def owner_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty role assignment table."""
    await reset_community()
    await seed_users(*_OWNER_IDS)
    yield postgres_db
    await reset_community()


class _FailingCleanupSession:
    """Session proxy that rejects the cleanup update."""

    def __init__(self, sess: AsyncSession) -> None:
        self._sess = sess

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        """Fail the cleanup update, pass everything else through."""
        if (
            isinstance(stmt, Update)
            and getattr(stmt, "table", None) is role_assignments
        ):
            raise RuntimeError("role assignment cleanup failed")
        return await self._sess.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the real session."""
        return getattr(self._sess, name)


def _install_failing_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the cleanup update fail inside the transfer transaction."""
    real_session = engine_module.session

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[_FailingCleanupSession]:
        async with real_session() as sess:
            yield _FailingCleanupSession(sess)

    monkeypatch.setattr(engine_module, "session", _session)


async def _owner_ids() -> list[int]:
    """Return every active owner id, ordered."""
    rows = await engine_module.fetch_all(
        role_assignments.select().where(
            role_assignments.c.role_key == "owner",
            role_assignments.c.status == "active",
        )
    )
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

    The revocation and the assignment share one transaction, so a failure
    between them cannot leave zero owner rows. Zero owners would leave the
    whole community without an owner until the next restart.
    """
    await users_roles.set_owner(61003)
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)
    _install_failing_cleanup(monkeypatch)

    with pytest.raises(RuntimeError, match="role assignment cleanup failed"):
        await users_roles.set_owner(61004)

    assert await _owner_ids() == [61003]
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)


async def test_set_owner_persistent_delete_failure_reraises_with_guidance(
    owner_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed transfer fails closed and points the operator at the table."""
    _install_failing_cleanup(monkeypatch)
    with (
        caplog.at_level(logging.ERROR, logger="tcbot.database.users_roles"),
        pytest.raises(RuntimeError, match="role assignment cleanup failed"),
    ):
        await users_roles.set_owner(61010)

    assert "role_assignments" in caplog.text
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
    interleaving their assignment and revocation. Without the lock the
    sequence assign A, assign B, revoke A, revoke B leaves no owner row.
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
