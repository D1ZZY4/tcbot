# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick summary delivery: edit the proof prompt in place, reply only as fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import kick_executor
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest


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

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        # * The executor is a Tester; the target holds no role, so the
        # * enforcement-time rank check passes.
        return "moderator" if user_id == 11 else None

    async def _logged(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)


def _run(bot: _FakeBot, **kwargs: Any) -> _FakeBot:
    asyncio.run(
        kick_executor.execute_kick(
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
    assert bot.edits[0]["args"][0] == 22
    assert bot.edits[0]["args"][1] == 44
    # * The summary is a rich outcome card: title, user row, reason row.
    assert "Kick Applied" in bot.edits[0]["kwargs"]["rich_message"].html
    assert "spam" in bot.edits[0]["kwargs"]["rich_message"].html
    assert bot.replies == []


def test_cancellation_during_demote_marks_the_kick_failed(
    _kick_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled demote must not leave a completed kick with no repair."""
    failed: list[int] = []

    async def _logged(*args: Any, **kwargs: Any) -> int:
        return 55

    async def _cancelled_demote(*args: Any, **kwargs: Any) -> None:
        raise asyncio.CancelledError

    async def _mark_failed(action_id: int) -> None:
        failed.append(action_id)

    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)
    monkeypatch.setattr(kick_executor, "demote_before_enforcement", _cancelled_demote)
    monkeypatch.setattr(db.kicks_db, "mark_kick_failed", _mark_failed)

    with pytest.raises(asyncio.CancelledError):
        _run(_FakeBot())
    assert failed == [55]


def test_summary_replies_when_prompt_unknown(_kick_no_io: None) -> None:
    bot = _run(_FakeBot())
    assert bot.edits == []
    assert len(bot.replies) == 1
    assert "Kick Applied" in bot.replies[0]["args"][0]
    assert "spam" in bot.replies[0]["args"][0]


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
    assert "Kick Applied" in bot.replies[0]["args"][0]
    assert "spam" in bot.replies[0]["args"][0]


def test_a_stranded_kick_queues_its_unban_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[tuple[int, int, int | None]] = []
    failed: list[int] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "moderator" if user_id == 11 else None

    async def _logged(*args: Any, **kwargs: Any) -> int:
        return 55

    async def _repair(action_id: int, chat_id: int, requested_by: int | None) -> int:
        queued.append((action_id, chat_id, requested_by))
        return 99

    async def _mark_failed(action_id: int) -> bool:
        failed.append(action_id)
        return True

    class _FailUnbanBot(_FakeBot):
        async def unban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("still banned")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)
    monkeypatch.setattr(db.kicks_db, "mark_kick_failed", _mark_failed)
    monkeypatch.setattr(db.enforcement_ledger, "queue_kick_unban_repair", _repair)

    bot = _run(_FailUnbanBot(), prompt_chat=22, prompt_id=44)

    assert queued == [(55, 22, 11)]
    assert failed == [55]
    assert bot.edits
    assert "WARNING" in bot.edits[0]["kwargs"]["rich_message"].html


def test_a_benign_retry_after_a_real_refusal_still_queues_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real first refusal is not erased by a benign error on the retry."""
    queued: list[tuple[int, int, int | None]] = []
    failed: list[int] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "moderator" if user_id == 11 else None

    async def _logged(*args: Any, **kwargs: Any) -> int:
        return 55

    async def _repair(action_id: int, chat_id: int, requested_by: int | None) -> int:
        queued.append((action_id, chat_id, requested_by))
        return 99

    async def _mark_failed(action_id: int) -> bool:
        failed.append(action_id)
        return True

    class _FlakyUnbanBot(_FakeBot):
        def __init__(self) -> None:
            super().__init__()
            self.unban_calls = 0

        async def unban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
            self.unban_calls += 1
            if self.unban_calls == 1:
                raise BadRequest("CHAT_ADMIN_REQUIRED")
            raise BadRequest("USER_NOT_PARTICIPANT")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)
    monkeypatch.setattr(db.kicks_db, "mark_kick_failed", _mark_failed)
    monkeypatch.setattr(db.enforcement_ledger, "queue_kick_unban_repair", _repair)

    _run(_FlakyUnbanBot(), prompt_chat=22, prompt_id=44)

    assert queued == [(55, 22, 11)]
    assert failed == [55]


def test_a_failed_ban_marks_the_kick_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kick whose ban never landed is not reported as a completed kick."""
    failed: list[int] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "moderator" if user_id == 11 else None

    async def _logged(*args: Any, **kwargs: Any) -> int:
        return 55

    async def _mark_failed(action_id: int) -> bool:
        failed.append(action_id)
        return True

    queued: list[int] = []

    async def _repair(action_id: int, chat_id: int, requested_by: int | None) -> int:
        queued.append(action_id)
        return 99

    class _FailBanBot(_FakeBot):
        async def ban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("not enough rights")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.kicks_db, "log_kick", _logged)
    monkeypatch.setattr(db.kicks_db, "mark_kick_failed", _mark_failed)
    monkeypatch.setattr(db.enforcement_ledger, "queue_kick_unban_repair", _repair)

    bot = _run(_FailBanBot())

    assert failed == [55]
    # * A ban that never landed cannot strand the user, so no no-op unban
    # * repair may be queued (the worker would rewrite history as completed).
    assert queued == []
    assert len(bot.replies) == 1
    assert "Couldn&#x27;t kick" in bot.replies[0]["args"][0]
