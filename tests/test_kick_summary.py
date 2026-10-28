# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick summary delivery: edit the proof prompt in place, reply only as fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import kicking_flow
from tcbot.modules.helper.workflows.demote_flow import Demote


class _FakeBot:
    """Bot double recording edits/replies and succeeding every moderation call."""

    def __init__(self, edit_outcome: Any = None) -> None:
        self._edit_outcome = edit_outcome
        self.edits: list[dict[str, Any]] = []
        self.replies: list[dict[str, Any]] = []

    async def ban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def unban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def send_message(self, *args: Any, **kwargs: Any) -> object:
        return object()

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> object:
        self.edits.append({"args": args, "kwargs": kwargs})
        if isinstance(self._edit_outcome, BaseException):
            raise self._edit_outcome
        return object()


class _FakeMsg:
    """Effective-message double recording reply_text calls."""

    def __init__(self, bot: _FakeBot) -> None:
        self._bot = bot

    async def reply_text(self, *args: Any, **kwargs: Any) -> object:
        self._bot.replies.append({"args": args, "kwargs": kwargs})
        return object()


class _FakeUser:
    id = 11
    first_name = "Mod"


class _FakeChat:
    id = 22
    title = "Group"


class _FakeUpdate:
    """Update double exposing message/user/chat like the kick executor needs."""

    def __init__(self, bot: _FakeBot) -> None:
        self.effective_message = _FakeMsg(bot)
        self.effective_user = _FakeUser()
        self.effective_chat = _FakeChat()


class _FakeCtx:
    def __init__(self, bot: _FakeBot) -> None:
        self.bot = bot


@pytest.fixture
def _kick_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub demote re-check and kick audit write so no database is touched."""

    async def _no_redemote(*args: Any, **kwargs: Any) -> None:
        return None

    async def _logged(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(Demote, "redemote_before_fanout", _no_redemote)
    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)


def _run(bot: _FakeBot, **kwargs: Any) -> _FakeBot:
    asyncio.run(
        kicking_flow.execute_kick(
            _FakeUpdate(bot),  # type: ignore[arg-type]
            _FakeCtx(bot),  # type: ignore[arg-type]
            33,
            "Target",
            "spam",
            **kwargs,
        )
    )
    return bot


def test_summary_edits_prompt_when_known(_kick_no_io: None) -> None:
    bot = _run(_FakeBot(), prompt_chat=22, prompt_id=44)
    assert len(bot.edits) == 1
    assert bot.edits[0]["kwargs"]["chat_id"] == 22
    assert bot.edits[0]["kwargs"]["message_id"] == 44
    assert "has been kicked" in bot.edits[0]["args"][0]
    assert bot.replies == []


def test_summary_replies_when_prompt_unknown(_kick_no_io: None) -> None:
    bot = _run(_FakeBot())
    assert bot.edits == []
    assert len(bot.replies) == 1
    assert "has been kicked" in bot.replies[0]["args"][0]


def test_summary_falls_back_to_reply_when_edit_fails(
    _kick_no_io: None,
) -> None:
    bot = _run(
        _FakeBot(edit_outcome=RuntimeError("gone")),
        prompt_chat=22,
        prompt_id=44,
    )
    assert len(bot.edits) == 1
    assert len(bot.replies) == 1
    assert "has been kicked" in bot.replies[0]["args"][0]
