# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The chat repoint: matched-return, failure, and cancellation semantics.

The repoint is inlined in the domain helpers: a basic group that becomes
a supergroup keeps its history under the new chat id.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import engine as engine_module
from tcbot.database import groups_db, mutes_db
from tcbot.database.base import chat_settings, connected_chats
from tests.postgres_support import (
    identity_db_call,
    literal_sql,
    reset_community,
    seed_chats,
    seed_users,
)

# * The helper that repoints a single decision type, with the statement it
# * is expected to send. A warning and a kick have no helper of their own:
# * the group repoint moves every decision in one transaction.
_REPOINT_CASES: tuple[tuple[Any, str], ...] = (
    (
        mutes_db,
        "UPDATE moderation_actions SET origin_chat_id=20 "
        "WHERE moderation_actions.action_type = 'mute' "
        "AND moderation_actions.origin_chat_id = 10",
    ),
)


class _Result:
    """Cursor result double carrying the affected row count."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Recorder:
    """Captures the statements a repoint sends to the database."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows: list[dict[str, Any]] = []
        self.affected: int = 0
        self.error: BaseException | None = None
        self.errors: list[BaseException | None] = []

    def _next_error(self) -> BaseException | None:
        """Return the error of the next statement, if one is queued."""
        if self.errors:
            return self.errors.pop(0)
        return self.error

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        return self.affected

    async def run_returning(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        return self.rows

    async def fetch_all(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        return self.rows

    async def fetch_one(self, stmt: Any) -> dict[str, Any] | None:
        """Record a single-row read and return the first queued row."""
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        return self.rows[0] if self.rows else None

    async def execute(self, stmt: Any) -> _Result:
        """Record a statement issued inside a transaction."""
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        return _Result(self.affected)

    async def run_transaction(self, op: Any) -> Any:
        """Run a transaction callback against the recorder."""
        return await op(self)


def _patch(monkeypatch: pytest.MonkeyPatch, module: Any, rec: _Recorder) -> None:
    """Point one module at the recorder instead of the database."""
    monkeypatch.setattr(module, "db_call", identity_db_call)
    monkeypatch.setattr(module, "run", rec.run, raising=False)
    monkeypatch.setattr(module, "run_returning", rec.run_returning, raising=False)
    monkeypatch.setattr(module, "fetch_all", rec.fetch_all, raising=False)
    monkeypatch.setattr(module, "fetch_one", rec.fetch_one, raising=False)
    monkeypatch.setattr(module, "run_transaction", rec.run_transaction, raising=False)


@pytest.mark.parametrize(("module", "expected"), _REPOINT_CASES)
def test_the_repoint_moves_every_row_of_the_old_chat(
    monkeypatch: pytest.MonkeyPatch, module: Any, expected: str
) -> None:
    """The update targets the old chat id and writes the new one."""
    rec = _Recorder()
    rec.affected = 3
    _patch(monkeypatch, module, rec)

    result = asyncio.run(module.migrate_records(10, 20))

    assert result is True
    assert literal_sql(rec.statements[0]) == expected


@pytest.mark.parametrize(("module", "expected"), _REPOINT_CASES)
def test_the_repoint_reports_no_match(
    monkeypatch: pytest.MonkeyPatch, module: Any, expected: str
) -> None:
    """A chat without history is not a migration."""
    rec = _Recorder()
    rec.affected = 0
    _patch(monkeypatch, module, rec)

    result = asyncio.run(module.migrate_records(10, 20))

    assert result is False
    _ = expected


@pytest.mark.parametrize(("module", "expected"), _REPOINT_CASES)
def test_the_repoint_propagates_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch, module: Any, expected: str
) -> None:
    """A database failure must not look like a finished migration.

    The caller collects the exception and logs it, so a failure stays
    visible instead of being reported as "nothing to move".
    """
    rec = _Recorder()
    rec.error = RuntimeError("db blip")
    _patch(monkeypatch, module, rec)

    async def _run_coro() -> None:
        with pytest.raises(RuntimeError, match="db blip"):
            await module.migrate_records(10, 20)

    asyncio.run(_run_coro())
    assert len(rec.statements) == 1
    _ = expected


@pytest.mark.parametrize(("module", "expected"), _REPOINT_CASES)
def test_the_repoint_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, module: Any, expected: str
) -> None:
    """A cancelled migration never reports success."""
    rec = _Recorder()
    rec.error = asyncio.CancelledError()
    _patch(monkeypatch, module, rec)

    async def _run_coro() -> None:
        with pytest.raises(asyncio.CancelledError):
            await module.migrate_records(10, 20)

    asyncio.run(_run_coro())
    assert len(rec.statements) == 1
    _ = expected


# ───────────────────────────── Groups ────────────────────────────── #


def test_the_group_repoint_moves_the_group_and_the_pending_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole group history follows the new chat id in one call."""
    rec = _Recorder()
    rec.rows = [{"was_active": True}]
    _patch(monkeypatch, groups_db, rec)

    result = asyncio.run(groups_db.migrate_group(10, 20))

    assert result is True
    # * The repoint is one database transaction: the identity, the
    # * configuration, the membership, the open request, and the
    # * decisions of the group all move through the same function.
    repoint_sql = literal_sql(rec.statements[0])
    assert "repoint_chat_records(10, 20)" in repoint_sql
    # * The summary is read as a flat column, so the caller does not
    # * depend on how the driver decodes the JSONB the function returns.
    assert "'was_active'" in repoint_sql


def test_the_group_repoint_reports_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat that is not connected is not a migration."""
    rec = _Recorder()
    rec.rows = []
    _patch(monkeypatch, groups_db, rec)

    result = asyncio.run(groups_db.migrate_group(10, 20))

    assert result is False


def test_the_group_repoint_propagates_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure must not look like a migration that found nothing.

    The caller collects the exception and logs it, so a failure stays
    visible instead of being reported as "not in the community".
    """
    rec = _Recorder()
    rec.error = RuntimeError("db blip")
    _patch(monkeypatch, groups_db, rec)

    async def _run_coro() -> None:
        with pytest.raises(RuntimeError, match="db blip"):
            await groups_db.migrate_group(10, 20)

    asyncio.run(_run_coro())
    assert len(rec.statements) == 1


def test_the_group_repoint_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled migration never reports success."""
    rec = _Recorder()
    rec.error = asyncio.CancelledError()
    _patch(monkeypatch, groups_db, rec)

    async def _run_coro() -> None:
        with pytest.raises(asyncio.CancelledError):
            await groups_db.migrate_group(10, 20)

    asyncio.run(_run_coro())
    assert len(rec.statements) == 1


@pytest.mark.postgres
async def test_the_group_repoint_merges_away_a_stale_row(
    postgres_db: str,
) -> None:
    """A target chat that already has a row converges instead of failing.

    The chat id is the primary key of the group registry, so the repoint
    cannot create a second row for the new chat. The stale old row stays
    known but inactive, so the history that refers to it stays readable,
    and the surviving row carries the configuration of the group.
    """
    await reset_community()
    await seed_users(1, 2)
    await seed_chats(10, 20)
    # * The old group chose a language; the new one has none.
    await engine_module.run(
        chat_settings.update()
        .where(chat_settings.c.chat_id == 10)
        .values(locale="id-ID")
    )

    result = await groups_db.migrate_group(10, 20)

    assert result is True
    rows = await engine_module.fetch_all(connected_chats.select())
    by_id = {int(row["chat_id"]): bool(row["is_active"]) for row in rows}
    # * The old chat stays known but inactive, so the history that
    # * refers to it stays readable.
    assert by_id[10] is False
    assert by_id[20] is True
    # * The group keeps the language it chose before the migration.
    settings = await engine_module.fetch_one(
        chat_settings.select().where(chat_settings.c.chat_id == 20)
    )
    assert settings is not None
    assert settings["locale"] == "id-ID"
    await reset_community()


@pytest.mark.postgres
async def test_the_group_repoint_keeps_a_disconnected_group_disconnected(
    postgres_db: str,
) -> None:
    """A group the operator disconnected must not be reconnected by a move.

    The repoint carries the connection state of the group it replaces.
    A group that was not managed before the move stays unmanaged after
    it, so the community fan-outs do not pull it in.
    """
    await reset_community()
    await seed_users(1, 2)
    await seed_chats(10)
    await engine_module.run(
        connected_chats.update()
        .where(connected_chats.c.chat_id == 10)
        .values(is_active=False)
    )

    await groups_db.migrate_group(10, 20)

    rows = await engine_module.fetch_all(connected_chats.select())
    by_id = {int(row["chat_id"]): bool(row["is_active"]) for row in rows}
    assert by_id.get(20) is False
    await reset_community()


@pytest.mark.postgres
async def test_the_group_repoint_keeps_the_surviving_row_decision(
    postgres_db: str,
) -> None:
    """A repoint must not undo the operator's decision about a chat.

    The target chat already has a registry row, and that row records a
    decision the operator took about it. The move keeps the row and its
    state: reactivating a disconnected group would pull it into the
    community fan-outs the operator took it out of.
    """
    await reset_community()
    await seed_users(1, 2)
    await seed_chats(10, 20)
    await engine_module.run(
        connected_chats.update()
        .where(connected_chats.c.chat_id == 20)
        .values(is_active=False)
    )

    await groups_db.migrate_group(10, 20)

    rows = await engine_module.fetch_all(connected_chats.select())
    by_id = {int(row["chat_id"]): bool(row["is_active"]) for row in rows}
    assert by_id[20] is False
    await reset_community()


@pytest.mark.postgres
async def test_the_group_repoint_caches_the_surviving_connection_state(
    postgres_db: str,
) -> None:
    """The cached connection state mirrors the row that survived.

    The target row may be an inactive one, because the operator had
    disconnected that group before the migration. Caching "connected"
    unconditionally would report a disconnected group as connected for the
    whole cache TTL and pull it into the federation fan-outs.
    """
    await reset_community()
    await seed_users(1, 2)
    await seed_chats(10, 20)
    await engine_module.run(
        connected_chats.update()
        .where(connected_chats.c.chat_id == 20)
        .values(is_active=False)
    )
    groups_db.connected_cache.invalidate(20)

    await groups_db.migrate_group(10, 20)

    assert await groups_db.is_connected(20) is False
    assert await groups_db.is_connected(20, fresh=True) is False
    await reset_community()
