# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Leaveall compensates a transient deactivation failure after the bot left."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest

from tcbot import database as db
from tcbot.modules import maintenance


class _Bot:
    def __init__(self, calls: list[tuple[str, int]]) -> None:
        self.calls = calls

    async def leave_chat(self, chat_id: int) -> None:
        self.calls.append(("leave", chat_id))


def test_a_transient_deactivation_failure_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    db_calls = 0

    async def _deactivate(chat_id: int) -> None:
        nonlocal db_calls
        db_calls += 1
        calls.append(("db", chat_id))
        if db_calls == 1:
            raise RuntimeError("transient database blip")

    async def _log(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(db.groups_db, "deactivate_group", _deactivate)
    monkeypatch.setattr(maintenance, "send_log", _log)

    result = asyncio.run(
        maintenance._leave_one(
            cast("Any", _Bot(calls)),
            {"chat_id": -100, "title": "Group"},
            1,
            "Admin",
        )
    )

    assert result.ok is True
    assert calls == [("leave", -100), ("db", -100), ("db", -100)]


def test_a_surviving_deactivation_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[tuple[str, int]] = []

    async def _deactivate(chat_id: int) -> None:
        calls.append(("db", chat_id))
        raise RuntimeError("database down")

    async def _log(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(db.groups_db, "deactivate_group", _deactivate)
    monkeypatch.setattr(maintenance, "send_log", _log)

    with caplog.at_level(logging.ERROR, logger="tcbot.modules.maintenance"):
        result = asyncio.run(
            maintenance._leave_one(
                cast("Any", _Bot(calls)),
                {"chat_id": -100, "title": "Group"},
                1,
                "Admin",
            )
        )

    assert result.ok is False
    assert calls == [("leave", -100), ("db", -100), ("db", -100)]
    assert "ghost group -100" in caplog.text
