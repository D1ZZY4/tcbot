# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active-ban uniqueness: the constraint names and the canonical record."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from tcbot.database import bans_db
from tcbot.database.bans_db import _queries, _writes
from tcbot.database.base import moderation_actions
from tests.postgres_support import (
    identity_db_call,
    literal_sql,
)


class _Recorder:
    """Captures the statements a ban helper sends to the engine."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows: list[dict[str, Any]] = []
        self.affected: int = 0
        self.run_error: BaseException | None = None

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        if self.run_error is not None:
            raise self.run_error
        return self.affected

    async def fetch_one(self, stmt: Any) -> dict[str, Any] | None:
        self.statements.append(stmt)
        return self.rows[0] if self.rows else None

    async def fetch_all(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        return self.rows

    async def fetch_count(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.affected


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch the ban helpers so every statement is recorded, not executed."""
    rec = _Recorder()
    monkeypatch.setattr(_writes, "db_call", identity_db_call)
    monkeypatch.setattr(_writes, "run", rec.run)
    monkeypatch.setattr(_queries, "db_call", identity_db_call)
    monkeypatch.setattr(_queries, "fetch_one", rec.fetch_one)
    monkeypatch.setattr(_queries, "fetch_all", rec.fetch_all)
    monkeypatch.setattr(_queries, "fetch_count", rec.fetch_count)
    return rec


def _unique_index() -> Any:
    """Return the partial unique index that guards the active bans."""
    for index in moderation_actions.indexes:
        if index.name == "uq_moderation_actions_active_ban":
            return index
    raise AssertionError("uq_moderation_actions_active_ban is not part of the schema")


def test_the_active_ban_uniqueness_is_a_partial_unique_index() -> None:
    """One active ban per user, enforced by the database."""
    index = _unique_index()

    assert index.unique is True
    assert [column.name for column in index.columns] == ["target_user_id"]
    predicate = index.dialect_options["postgresql"]["where"]
    assert "action_type = 'ban'" in str(predicate)
    assert "status = 'active'" in str(predicate)


def test_the_external_reference_has_its_own_unique_constraint() -> None:
    """The public reference stays unique across the whole history."""
    constraints = [
        constraint
        for constraint in moderation_actions.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_moderation_actions_external_ref"
    ]
    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == ["external_ref"]


def test_the_external_reference_accepts_only_the_public_format() -> None:
    """The reference travels in a deep link, so it has a fixed shape."""
    checks = [
        constraint
        for constraint in moderation_actions.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_moderation_actions_external_ref"
    ]
    assert len(checks) == 1
    assert "^[a-z0-9]{10,32}$" in str(checks[0].sqltext)


def test_the_reacted_constraint_names_exist_in_the_schema() -> None:
    """The names the code branches on are the names the schema declares."""
    index_names = {index.name for index in moderation_actions.indexes}
    constraint_names = {
        constraint.name
        for constraint in moderation_actions.constraints
        if constraint.name
    }

    assert bans_db.CONSTRAINT_ACTIVE_USER in index_names
    assert bans_db.CONSTRAINT_EXTERNAL_REF in constraint_names


def test_deactivate_extra_active_bans_keeps_the_canonical_record(
    recorder: _Recorder,
) -> None:
    """Every other active ban of the user is revoked."""
    recorder.affected = 2

    count = asyncio.run(bans_db.deactivate_extra_active_bans(42, "keep"))

    assert count == 2
    sql = literal_sql(recorder.statements[0])
    assert sql.startswith("UPDATE moderation_actions SET status='revoked'")
    assert "moderation_actions.target_user_id = 42" in sql
    assert "moderation_actions.action_type = 'ban'" in sql
    assert "moderation_actions.status = 'active'" in sql
    assert "moderation_actions.external_ref != 'keep'" in sql


def test_deactivate_extra_active_bans_is_a_noop_without_duplicates(
    recorder: _Recorder,
) -> None:
    """A user with one active ban has nothing to revoke."""
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
    assert "moderation_actions.target_user_id = 42" in sql
    assert "moderation_actions.action_type = 'ban'" in sql
    assert "moderation_actions.status = 'active'" in sql
    assert "external_ref !=" not in sql


def test_the_active_ban_read_orders_by_the_newest_decision(
    recorder: _Recorder,
) -> None:
    """The canonical record is the newest active decision."""
    recorder.rows = []

    asyncio.run(bans_db.get_active_ban(42))

    sql = literal_sql(recorder.statements[0])
    assert "moderation_actions.action_type = 'ban'" in sql
    assert "moderation_actions.status = 'active'" in sql
    assert "ORDER BY moderation_actions.created_at DESC" in sql
