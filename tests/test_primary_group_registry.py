# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The main group is anchored in the registry but never federation-connected."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import groups_db


class _StatementCapture:
    """Record the executed statements and the values they carry."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


class _FakeCache:
    """Minimal cache double; the seeding only writes through put/invalidate."""

    def put(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def invalidate(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def test_primary_group_is_anchored_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_primary_group never flips the main group to an active connection."""
    capture = _StatementCapture()

    async def _run_transaction(op: Any) -> None:
        await op(capture)

    monkeypatch.setattr(groups_db, "run_transaction", _run_transaction)
    monkeypatch.setattr(groups_db, "connected_cache", _FakeCache())
    monkeypatch.setattr(groups_db, "active_groups_cache", _FakeCache())

    asyncio.run(groups_db.ensure_primary_group(-1003872207988, "Main"))

    # * The telegram_chats identity row and the connected_chats anchor row.
    assert len(capture.statements) == 2
    connected_stmt = capture.statements[1]
    compiled = str(connected_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "is_active" in compiled
    assert "false" in compiled.lower(), compiled
    # * An existing ACTIVE row from an older deployment must be repaired to
    # * inactive, so conflict forces the same value instead of preserving it.
    assert "ON CONFLICT" in compiled
    assert "DO UPDATE SET is_active = false" in compiled
