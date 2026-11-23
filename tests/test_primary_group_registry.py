# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The main group is anchored in the registry but never federation-connected."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tcbot.database import groups_db
from tcbot.database.connection_options import schema_options


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


def test_primary_chat_id_is_published_to_the_database_session() -> None:
    """The enforcement trigger needs the main group id as a session GUC."""
    options = schema_options("public", primary_chat_id=-1003872207988)
    assert "-c search_path=public" in options
    assert "-c tcbot.primary_chat_id=-1003872207988" in options
    assert "tcbot.primary_chat_id" not in schema_options("public")


def test_enforcement_target_trigger_admits_the_primary_chat() -> None:
    """The trigger must not reject the inactive main group it is told about."""
    sql = (
        Path(__file__).resolve().parents[1]
        / "tcbot"
        / "database"
        / "schema"
        / "functions.sql"
    ).read_text(encoding="utf-8")
    start = sql.index("prepare_moderation_enforcement_target")
    body = sql[start : sql.index("$$;", start)]
    assert body.count("tcbot.primary_chat_id") == 2
    assert "cc.is_active" in body
