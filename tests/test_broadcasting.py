# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Broadcast fan-out counts benign refusals apart from transient failures."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from telegram.error import BadRequest, TimedOut

from tcbot import database as db
from tcbot.modules import broadcast


class _StatusMsg:
    def __init__(self) -> None:
        self.edits: list[str] = []

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)


class _FakeMsg:
    def __init__(self, text: str) -> None:
        self.text = text
        self.reply_to_message = None
        self.replies: list[str] = []
        self.status = _StatusMsg()
        self.chat = SimpleNamespace(id=-1001, type="supergroup")

    async def reply_text(self, text: str, **kwargs: Any) -> _StatusMsg:
        self.replies.append(text)
        return self.status


class _FakeBot:
    def __init__(self, failures: dict[int, Exception]) -> None:
        self.failures = failures
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        if chat_id in self.failures:
            raise self.failures[chat_id]
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=1)


def _update(msg: _FakeMsg) -> Any:
    return SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=7, first_name="Admin"),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        callback_query=None,
    )


def _run(monkeypatch: pytest.MonkeyPatch, failures: dict[int, Exception]) -> _FakeMsg:
    groups = [
        {"chat_id": 101, "title": "A"},
        {"chat_id": 102, "title": "B"},
        {"chat_id": 103, "title": "C"},
    ]

    async def _active() -> Any:
        return groups

    async def _role(uid: int, *, fresh: bool = False) -> str | None:
        return "admin"

    async def _owner() -> int:
        return 999

    async def _connected(chat_id: int, *, fresh: bool = False) -> bool:
        return True

    monkeypatch.setattr(db.groups_db, "active_groups", _active)
    monkeypatch.setattr(db.groups_db, "is_connected", _connected)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    msg = _FakeMsg("/tcbroadcast hello federation")
    ctx = SimpleNamespace(bot=_FakeBot(failures), user_data={})
    asyncio.run(broadcast.cmd_broadcast(_update(msg), ctx))  # type: ignore[arg-type]
    return msg


def test_broadcast_total_success_counts_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msg = _run(monkeypatch, {})
    assert msg.status.edits
    text = msg.status.edits[0]
    assert "`3`" in text
    assert "`0`" in text


def test_broadcast_counts_only_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msg = _run(
        monkeypatch,
        {
            101: BadRequest("USER_NOT_PARTICIPANT"),
            102: TimedOut("slow"),
        },
    )
    assert msg.status.edits
    text = msg.status.edits[0]
    # * Benign refusal is not a failure.
    assert "`2`" in text
    assert "`1`" in text


def test_broadcast_refuses_disconnected_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [{"chat_id": 101, "title": "A"}]

    async def _active() -> Any:
        return groups

    async def _role(uid: int, *, fresh: bool = False) -> str | None:
        return "admin"

    async def _owner() -> int:
        return 999

    async def _not_connected(chat_id: int, *, fresh: bool = False) -> bool:
        return False

    monkeypatch.setattr(db.groups_db, "active_groups", _active)
    monkeypatch.setattr(db.groups_db, "is_connected", _not_connected)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    msg = _FakeMsg("/tcbroadcast hello federation")
    bot = _FakeBot({})
    ctx = SimpleNamespace(bot=bot, user_data={})
    asyncio.run(broadcast.cmd_broadcast(_update(msg), ctx))  # type: ignore[arg-type]
    # * Disconnected origin refuses before fan-out.
    assert bot.sent == []
    assert msg.status.edits == []
