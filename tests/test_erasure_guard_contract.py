# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The erasure guard keeps a cleared profile from being written back."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tcbot.database import erasure_db

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = _ROOT / "tcbot/database/schema"


def _identity_sql() -> str:
    return (_SCHEMA / "functions/identity.sql").read_text(encoding="utf-8")


def _triggers_sql() -> str:
    return (_SCHEMA / "triggers.sql").read_text(encoding="utf-8")


def _maintenance_sql() -> str:
    return (_SCHEMA / "functions/maintenance.sql").read_text(encoding="utf-8")


def test_the_guard_function_rejects_a_repopulated_profile() -> None:
    sql = _identity_sql()
    assert "guard_erased_user_identity()" in sql
    assert "ck_telegram_users_erased_identity" in sql
    assert "OLD.erased_at IS NOT NULL" in sql


def test_the_guard_is_attached_to_the_identity_columns() -> None:
    trigger = next(
        line
        for line in _triggers_sql().splitlines()
        if "trg_telegram_users_guard_erased_identity" in line
    )
    assert "BEFORE UPDATE OF" in trigger
    for column in ("username", "first_name", "last_name", "language_code"):
        assert column in trigger


def test_a_repeat_erasure_is_allowed() -> None:
    maintenance = _maintenance_sql()
    assert "was already erased" not in maintenance
    assert "A repeat request is allowed" in maintenance


def test_an_erasure_request_runs_on_the_write_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queueing an erasure inserts rows, so it must not use a read connection."""
    seen: list[str] = []

    async def _db_call(op: object, **kwargs: object) -> object:
        return await op()  # type: ignore[operator]

    async def _write(stmt: object) -> list[dict[str, int]]:
        seen.append(str(stmt))
        return [{"request_id": 7}]

    monkeypatch.setattr(erasure_db, "db_call", _db_call)
    monkeypatch.setattr(erasure_db, "run_returning", _write)

    assert asyncio.run(erasure_db.request_erasure(3, "account deletion")) == 7
    assert len(seen) == 1
    assert "request_user_erasure" in seen[0]
    assert "AS request_id" in seen[0]


def test_an_erasure_request_without_an_id_keeps_the_zero_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NULL return from the guard must not turn into a TypeError."""

    async def _db_call(op: object, **kwargs: object) -> object:
        return await op()  # type: ignore[operator]

    async def _write(stmt: object) -> list[dict[str, object]]:
        _ = stmt
        return [{"request_id": None}]

    monkeypatch.setattr(erasure_db, "db_call", _db_call)
    monkeypatch.setattr(erasure_db, "run_returning", _write)

    assert asyncio.run(erasure_db.request_erasure(3, "account deletion")) == 0


def test_the_migration_chain_has_one_head() -> None:
    versions = _ROOT / "alembic/versions"
    revisions: dict[str, str | None] = {}
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = next(
            line.split('"')[1]
            for line in text.splitlines()
            if line.startswith("revision:")
        )
        down: str | None = None
        for line in text.splitlines():
            if not line.startswith("down_revision:"):
                continue
            raw = line.split("=", 1)[1].strip()
            down = None if raw == "None" else raw.strip("\"'")
            break
        revisions[revision] = down
    parents = {down for down in revisions.values() if down}
    heads = set(revisions) - parents
    assert heads == {"0022_reconcile_primary_chat"}
