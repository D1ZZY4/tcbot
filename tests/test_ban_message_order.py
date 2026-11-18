# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban composition keeps the newest log and appeal message reference."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from tcbot.database.bans_db import _compose


def test_the_message_read_keeps_the_newest_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The append-only history must expose the latest message, not the first."""
    captured: list[str] = []

    async def _db_call(op: Any, **kwargs: Any) -> Any:
        return await op()

    async def _fetch_all(stmt: Any) -> list[dict[str, Any]]:
        captured.append(str(stmt.compile(dialect=postgresql.dialect())))
        return [
            {"action_id": 1, "message_kind": "log", "message_id": 80},
            {"action_id": 1, "message_kind": "log", "message_id": 90},
        ]

    monkeypatch.setattr(_compose, "db_call", _db_call)
    monkeypatch.setattr(_compose, "fetch_all", _fetch_all)

    messages = asyncio.run(_compose._messages_for([1]))

    assert "ORDER BY moderation_messages.id" in captured[0]
    assert messages == {1: {"log": 90}}
