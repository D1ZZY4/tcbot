# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-ban uniqueness: the constraint names and the canonical record."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError

from tcbot.database import bans_db
from tcbot.database.base import bans
from tests.postgres_support import (
    compile_sql,
    identity_db_call,
    literal_sql,
    stmt_params,
)


class _FakeDiagnostic:
    """The PostgreSQL error diagnostic that names the violated constraint."""

    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _FakeDriverError(Exception):
    """Driver error double carrying the violated constraint name."""

    def __init__(self, name: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{name}"')
        self.diag = _FakeDiagnostic(name)


def _unique_violation(name: str) -> IntegrityError:
    """Return the integrity error PostgreSQL raises for *name*."""
    return IntegrityError("INSERT INTO bans ...", {}, _FakeDriverError(name))


class _Recorder:
    """Captures the statements a ban helper sends to the engine."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows: list[dict[str, Any]] = []
        self.affected: int = 0
        self.insert_error: BaseException | None = None
        self.read_error: BaseException | None = None
        self.run_error: BaseException | None = None
        # * A queue of per-statement errors, so a retry can fail once and
        # * then succeed.
        self.errors: list[BaseException | None] = []

    def _next_error(self) -> BaseException | None:
        """Return the error of the next statement, if one is queued."""
        if self.errors:
            return self.errors.pop(0)
        return self.insert_error

    async def run_returning(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        error = self._next_error()
        if error is not None:
            raise error
        if self.rows:
            return self.rows
        # * The engine returns the stored row. The recorder mirrors that
        # * by echoing the bound values of the insert back.
        return [dict(stmt_params(stmt))]

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        if self.run_error is not None:
            raise self.run_error
        return self.affected

    async def fetch_one(self, stmt: Any) -> dict[str, Any] | None:
        self.statements.append(stmt)
        if self.read_error is not None:
            raise self.read_error
        return self.rows[0] if self.rows else None

    async def fetch_count(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.affected


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch the ban helpers so every statement is recorded, not executed."""
    rec = _Recorder()
    monkeypatch.setattr(bans_db, "db_call", identity_db_call)
    monkeypatch.setattr(bans_db, "run_returning", rec.run_returning)
    monkeypatch.setattr(bans_db, "run", rec.run)
    monkeypatch.setattr(bans_db, "fetch_one", rec.fetch_one)
    monkeypatch.setattr(bans_db, "fetch_all", rec.fetch_one)
    monkeypatch.setattr(bans_db, "fetch_count", rec.fetch_count)
    return rec


def _unique_index() -> Any:
    """Return the partial unique index that guards the active bans."""
    for index in bans.indexes:
        if index.name == "uq_bans_active_user":
            return index
    raise AssertionError("uq_bans_active_user is not part of the schema")


def test_the_active_ban_uniqueness_is_a_partial_unique_index() -> None:
    """One active ban per user, enforced by the database."""
    index = _unique_index()

    assert index.unique is True
    assert [column.name for column in index.columns] == ["banned_user_id"]
    predicate = index.dialect_options["postgresql"]["where"]
    assert str(predicate) == "is_active"


def test_the_ban_id_has_its_own_unique_constraint() -> None:
    """The public ban id stays unique across the whole history."""
    constraints = [
        constraint
        for constraint in bans.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_bans_ban_id"
    ]
    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == ["ban_id"]


def test_the_reacted_constraint_names_exist_in_the_schema() -> None:
    """The names the code branches on are the names the schema declares."""
    index_names = {index.name for index in bans.indexes}
    constraint_names = {
        constraint.name for constraint in bans.constraints if constraint.name
    }

    assert bans_db._CONSTRAINT_ACTIVE_USER in index_names
    assert bans_db._CONSTRAINT_BAN_ID in constraint_names


def test_create_ban_inserts_an_active_ban(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The insert carries the new ban and marks it active."""
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: "generated")

    doc = asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0))

    assert doc.get("ban_id") == "generated"
    assert doc.get("banned_user_id") == 42
    assert doc.get("is_active") is True
    sql = compile_sql(recorder.statements[0])
    assert sql.startswith("INSERT INTO bans")
    params = stmt_params(recorder.statements[0])
    assert params["banned_user_id"] == 42
    assert params["is_active"] is True


def test_create_ban_reuses_the_winning_record_on_a_race(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent ban loses the race and keeps the canonical record."""
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: "generated")
    recorder.insert_error = _unique_violation("uq_bans_active_user")
    recorder.rows = [{"ban_id": "winner", "banned_user_id": 42, "is_active": True}]

    doc = asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0))

    assert doc.get("ban_id") == "winner"
    # * The loser reads the active ban back and hands it to the caller,
    # * so the moderation continues instead of failing on the race.
    read_sql = compile_sql(recorder.statements[1])
    assert "bans.is_active IS true" in read_sql
    assert "ORDER BY bans.timestamp DESC, bans.ban_id DESC" in read_sql


def test_create_ban_retries_a_generated_id_collision(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated id that collides is swapped for a fresh one.

    The caller never supplied the id, so a collision must not fail the
    moderation action: the insert is retried with another random id.
    """
    ids = iter(["first", "second"])
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: next(ids))
    recorder.errors = [
        _unique_violation("uq_bans_ban_id"),
        None,
    ]

    doc = asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0))

    assert doc.get("ban_id") == "second"
    assert len(recorder.statements) == 2
    assert stmt_params(recorder.statements[1])["ban_id"] == "second"


def test_create_ban_reraises_an_explicit_id_collision(
    recorder: _Recorder,
) -> None:
    """An explicit id that is taken must not be swapped silently.

    The caller reuses the id for the appeal link and the log patch, so
    handing back a different record would orphan those references.
    """
    recorder.errors = [_unique_violation("uq_bans_ban_id")]

    with pytest.raises(IntegrityError):
        asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0, "explicit"))

    assert len(recorder.statements) == 1


def test_create_ban_reraises_another_integrity_error(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the known constraints are handled; the rest are real defects."""
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: "generated")
    recorder.errors = [_unique_violation("uq_something_else")]

    with pytest.raises(IntegrityError):
        asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0))

    assert len(recorder.statements) == 1


def test_create_ban_reraises_when_the_taken_id_is_the_winner(
    recorder: _Recorder,
) -> None:
    """An explicit id that is already taken must not be silently swapped.

    The caller reuses the id for the appeal link and the log patch, so
    handing back a different record would orphan those references.
    """
    recorder.insert_error = _unique_violation("uq_bans_active_user")
    recorder.rows = [{"ban_id": "takenid", "banned_user_id": 42, "is_active": True}]

    with pytest.raises(IntegrityError):
        asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0, "takenid"))


def test_create_ban_reraises_when_the_winner_is_gone(
    recorder: _Recorder,
) -> None:
    """A lost race without a readable winner stays a failure."""
    recorder.insert_error = _unique_violation("uq_bans_active_user")
    recorder.rows = []

    with pytest.raises(IntegrityError):
        asyncio.run(bans_db.create_ban(42, "spam", 7, 1, 0, "someid"))


def test_deactivate_extra_active_bans_keeps_the_canonical_record(
    recorder: _Recorder,
) -> None:
    """Every other active ban of the user is deactivated."""
    recorder.affected = 2

    count = asyncio.run(bans_db.deactivate_extra_active_bans(42, "keep"))

    assert count == 2
    sql = literal_sql(recorder.statements[0])
    assert sql.startswith("UPDATE bans SET is_active=false")
    assert "bans.banned_user_id = 42" in sql
    assert "bans.is_active IS true" in sql
    assert "bans.ban_id != 'keep'" in sql


def test_deactivate_extra_active_bans_is_a_noop_without_duplicates(
    recorder: _Recorder,
) -> None:
    """A user with one active ban has nothing to deactivate."""
    recorder.affected = 0

    count = asyncio.run(bans_db.deactivate_extra_active_bans(42, "keep"))

    assert count == 0
    assert len(recorder.statements) == 1


def test_deactivate_all_active_bans_clears_every_active_record(
    recorder: _Recorder,
) -> None:
    """The unban path clears every active ban of the user."""
    recorder.affected = 3

    count = asyncio.run(bans_db.deactivate_all_active_bans(42))

    assert count == 3
    sql = literal_sql(recorder.statements[0])
    assert "bans.banned_user_id = 42" in sql
    assert "bans.is_active IS true" in sql
    assert "ban_id !=" not in sql
