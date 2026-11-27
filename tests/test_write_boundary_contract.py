# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Writes must use the transactional boundary, not the autocommit read path."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import groups_db
from tcbot.database.rules_db import read as rules_read


async def _inline_db_call(op: Any, **_kwargs: Any) -> Any:
    return await op()


async def _no_read(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("a write must not use the autocommit read connection")


def test_group_migration_runs_on_the_write_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repointing a group writes six tables in one statement."""
    seen: list[str] = []

    async def _write(stmt: Any) -> list[dict[str, Any]]:
        seen.append(str(stmt))
        return [{"was_active": True}]

    async def _active(_chat_id: int) -> bool:
        return True

    monkeypatch.setattr(groups_db, "db_call", _inline_db_call)
    monkeypatch.setattr(groups_db, "run_returning", _write)
    monkeypatch.setattr(groups_db, "fetch_one", _no_read)
    monkeypatch.setattr(groups_db, "_group_is_active", _active)

    assert asyncio.run(groups_db.migrate_group(-100, -200)) is True
    assert len(seen) == 1
    assert "repoint_chat_records" in seen[0]


def test_rule_acknowledgement_runs_on_the_write_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording an acknowledgement inserts a row, so it must commit."""
    seen: list[str] = []

    async def _write(stmt: Any) -> list[dict[str, Any]]:
        seen.append(str(stmt))
        return [{"id": 9}]

    monkeypatch.setattr(rules_read, "db_call", _inline_db_call)
    monkeypatch.setattr(rules_read, "run_returning", _write)
    monkeypatch.setattr(rules_read, "fetch_all", _no_read)

    assert asyncio.run(rules_read.record_acknowledgement(4, 7, -100, 12)) is True
    assert len(seen) == 1
    assert "rule_acknowledgements" in seen[0]
