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
from tcbot.database import groups_db, kicks_db, mutes_db, warns_db
from tcbot.database.base import federated_groups
from tcbot.utils.time_and_date import utc_now
from tests.postgres_support import identity_db_call, literal_sql

# * The helpers that repoint a single table.
_REPOINT_CASES: tuple[tuple[Any, str], ...] = (
    (kicks_db, "kicks"),
    (mutes_db, "mutes"),
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


class _FakeDiagnostic:
    """The PostgreSQL error diagnostic that names the violated constraint."""

    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _FakeDriverError(Exception):
    """Driver error double carrying the violated constraint name."""

    def __init__(self, name: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{name}"')
        self.diag = _FakeDiagnostic(name)


def _patch(monkeypatch: pytest.MonkeyPatch, module: Any, rec: _Recorder) -> None:
    """Point one module at the recorder instead of the database."""
    monkeypatch.setattr(module, "db_call", identity_db_call)
    monkeypatch.setattr(module, "run", rec.run, raising=False)
    monkeypatch.setattr(module, "run_returning", rec.run_returning, raising=False)
    monkeypatch.setattr(module, "fetch_all", rec.fetch_all, raising=False)
    monkeypatch.setattr(module, "fetch_one", rec.fetch_all, raising=False)
    monkeypatch.setattr(module, "run_transaction", rec.run_transaction, raising=False)


@pytest.mark.parametrize(("module", "table"), _REPOINT_CASES)
def test_the_repoint_moves_every_row_of_the_old_chat(
    monkeypatch: pytest.MonkeyPatch, module: Any, table: str
) -> None:
    """The update targets the old chat id and writes the new one."""
    rec = _Recorder()
    rec.affected = 3
    _patch(monkeypatch, module, rec)

    result = asyncio.run(module.migrate_records(10, 20))

    assert result is True
    sql = literal_sql(rec.statements[0])
    assert sql == f"UPDATE {table} SET chat_id=20 WHERE {table}.chat_id = 10"


@pytest.mark.parametrize(("module", "table"), _REPOINT_CASES)
def test_the_repoint_reports_no_match(
    monkeypatch: pytest.MonkeyPatch, module: Any, table: str
) -> None:
    """A chat without history is not a migration."""
    rec = _Recorder()
    rec.affected = 0
    _patch(monkeypatch, module, rec)

    result = asyncio.run(module.migrate_records(10, 20))

    assert result is False
    _ = table


@pytest.mark.parametrize(("module", "table"), _REPOINT_CASES)
def test_the_repoint_swallows_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch, module: Any, table: str
) -> None:
    """A database failure ends the migration without raising."""
    rec = _Recorder()
    rec.error = RuntimeError("db blip")
    _patch(monkeypatch, module, rec)

    result = asyncio.run(module.migrate_records(10, 20))

    assert result is False
    assert len(rec.statements) == 1
    _ = table


@pytest.mark.parametrize(("module", "table"), _REPOINT_CASES)
def test_the_repoint_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, module: Any, table: str
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
    _ = table


# ─────────────────────────── Warn counters ───────────────────────── #


def test_the_warn_repoint_moves_the_history_and_the_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warn history and the counter rows follow the chat."""
    rec = _Recorder()
    rec.affected = 2
    rec.rows = [{"user_id": 42, "count": 3}]
    _patch(monkeypatch, warns_db, rec)

    result = asyncio.run(warns_db.migrate_records(10, 20))

    assert result is True
    history_sql = literal_sql(rec.statements[0])
    assert history_sql == "UPDATE warns SET chat_id=20 WHERE warns.chat_id = 10"
    merge_statements = [literal_sql(stmt) for stmt in rec.statements]
    assert any("DELETE FROM warn_counts" in sql for sql in merge_statements)
    assert any("INSERT INTO warn_counts" in sql for sql in merge_statements)


def test_the_warn_repoint_merges_the_counter_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counter of the old chat is added to the counter of the new one."""
    rec = _Recorder()
    rec.affected = 1
    rec.rows = [{"user_id": 42, "count": 3}]
    _patch(monkeypatch, warns_db, rec)

    asyncio.run(warns_db.migrate_records(10, 20))

    merge = [
        literal_sql(stmt)
        for stmt in rec.statements
        if "INSERT INTO warn_counts" in literal_sql(stmt)
    ]
    assert len(merge) == 1
    assert "warn_counts.count + 3" in merge[0]


def test_the_warn_repoint_reports_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat without warns is not a migration."""
    rec = _Recorder()
    rec.affected = 0
    rec.rows = []
    _patch(monkeypatch, warns_db, rec)

    result = asyncio.run(warns_db.migrate_records(10, 20))

    assert result is False


def test_the_warn_repoint_swallows_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure ends the migration without raising."""
    rec = _Recorder()
    rec.error = RuntimeError("db blip")
    _patch(monkeypatch, warns_db, rec)

    result = asyncio.run(warns_db.migrate_records(10, 20))

    assert result is False
    assert len(rec.statements) == 1


def test_the_warn_repoint_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled migration never reports success."""
    rec = _Recorder()
    rec.error = asyncio.CancelledError()
    _patch(monkeypatch, warns_db, rec)

    async def _run_coro() -> None:
        with pytest.raises(asyncio.CancelledError):
            await warns_db.migrate_records(10, 20)

    asyncio.run(_run_coro())
    assert len(rec.statements) == 1


# ───────────────────────────── Groups ────────────────────────────── #


def test_the_group_repoint_moves_the_group_and_the_pending_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both group tables follow the new chat id."""
    rec = _Recorder()
    rec.affected = 1
    _patch(monkeypatch, groups_db, rec)

    result = asyncio.run(groups_db.migrate_group(10, 20))

    assert result is True
    group_sql = literal_sql(rec.statements[0])
    assert (
        group_sql
        == "UPDATE federated_groups SET chat_id=20 WHERE federated_groups.chat_id = 10"
    )
    pending_sql = literal_sql(rec.statements[1])
    assert (
        pending_sql
        == "UPDATE pending_joins SET chat_id=20 WHERE pending_joins.chat_id = 10"
    )


def test_the_group_repoint_reports_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat that is not connected is not a migration."""
    rec = _Recorder()
    rec.affected = 0
    _patch(monkeypatch, groups_db, rec)

    result = asyncio.run(groups_db.migrate_group(10, 20))

    assert result is False


def test_the_group_repoint_swallows_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure ends the migration without raising."""
    rec = _Recorder()
    rec.error = RuntimeError("db blip")
    _patch(monkeypatch, groups_db, rec)

    result = asyncio.run(groups_db.migrate_group(10, 20))

    assert result is False
    # * The failing table ends the migration: the group row is the first
    # * one and its failure stops the pending join update.
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

    The chat id is the primary key of the group table, so the repoint
    cannot create a second row for the new chat. The stale old row is
    merged into the surviving row and the migration still succeeds.
    """
    await engine_module.run(federated_groups.delete())
    await engine_module.run(
        federated_groups.insert().values(
            chat_id=10,
            title="Old group",
            added_by=1,
            added_date=utc_now(),
            is_active=True,
            locale="id-ID",
        )
    )
    await engine_module.run(
        federated_groups.insert().values(
            chat_id=20,
            title="New group",
            added_by=2,
            added_date=utc_now(),
            is_active=True,
            locale=None,
        )
    )

    result = await groups_db.migrate_group(10, 20)

    assert result is True
    rows = await engine_module.fetch_all(federated_groups.select())
    assert [int(row["chat_id"]) for row in rows] == [20]
    # * The group keeps the language it chose before the migration.
    assert rows[0]["locale"] == "id-ID"
    await engine_module.run(federated_groups.delete())


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
    await engine_module.run(federated_groups.delete())
    await engine_module.run(
        federated_groups.insert().values(
            chat_id=10,
            title="Old group",
            added_by=1,
            added_date=utc_now(),
            is_active=True,
            locale=None,
        )
    )
    await engine_module.run(
        federated_groups.insert().values(
            chat_id=20,
            title="New group",
            added_by=2,
            added_date=utc_now(),
            is_active=False,
            locale=None,
        )
    )
    groups_db.connected_cache.invalidate(20)

    await groups_db.migrate_group(10, 20)

    assert await groups_db.is_connected(20) is False
    assert await groups_db.is_connected(20, fresh=True) is False
    await engine_module.run(federated_groups.delete())
