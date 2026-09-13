# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick entry guards: private chats are refused before any role or demote I/O."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules import kicking
from tcbot.modules.helper import replies

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeChat:
    def __init__(self, chat_id: int, chat_type: str) -> None:
        self.id = chat_id
        self.type = chat_type
        self.title = "chat"


class _FakeUser:
    def __init__(self, uid: int) -> None:
        self.id = uid
        self.first_name = "Admin"
        self.username = "admin"


class _FakeMsg:
    def __init__(self, text: str, chat: _FakeChat) -> None:
        self.text = text
        self.chat = chat
        self.reply_to_message = None
        self.entities: tuple = ()
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> str:
        self.replies.append(text)
        return text


class _FakeUpdate:
    def __init__(self, msg: _FakeMsg, user: _FakeUser, chat: _FakeChat) -> None:
        self.effective_message = msg
        self.effective_user = user
        self.effective_chat = chat
        self.callback_query = None


class _FakeCtx:
    def __init__(self) -> None:
        self.user_data: dict[str, Any] = {}
        self.bot = None


@pytest.fixture
def _staff_caller(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Stub role reads so the Tester-ranked caller passes the decorators."""

    async def _owner_id() -> int:
        return 999

    async def _role(uid: int) -> str | None:
        return "tester"

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner_id)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    yield


def _run(update: _FakeUpdate, ctx: _FakeCtx) -> Any:
    return asyncio.run(kicking.cmd_kick(update, ctx))  # type: ignore[arg-type]


def test_kick_in_private_chat_refused(
    _staff_caller: None,
) -> None:
    chat = _FakeChat(7146954165, "private")
    msg = _FakeMsg("/tckick 5868266754 spam", chat)
    ctx = _FakeCtx()
    result = _run(_FakeUpdate(msg, _FakeUser(111), chat), ctx)
    assert result == ConversationHandler.END
    assert msg.replies == [replies.err_group_only(plain=True)]
    assert not any(key.startswith("kick_") for key in ctx.user_data)


def test_kick_in_group_passes_guard(
    _staff_caller: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A group chat must sail past the guard into target resolution."""
    chat = _FakeChat(-100123, "supergroup")
    msg = _FakeMsg("/tckick", chat)
    ctx = _FakeCtx()
    result = _run(_FakeUpdate(msg, _FakeUser(111), chat), ctx)
    assert result == ConversationHandler.END
    # * No target given: the guard passed and resolution replied instead.
    assert msg.replies == [replies.err_cannot_resolve(plain=True)]
