# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Writes must use the transactional boundary, not the autocommit read path."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import groups_db


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
