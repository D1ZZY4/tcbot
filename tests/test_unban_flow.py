# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""execute_unban fails closed and names missed groups."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import unban_flow
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t


class _FakeMsg:
    """Message double recording replies."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()


class _FakeBot:
    """Bot double with scripted unban outcomes, recording log sends."""

    def __init__(self, fail_ids: set[int] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.unbanned: list[int] = []
        self.logs: list[str] = []

    async def unban_chat_member(
        self, chat_id: int, user_id: int, **kwargs: Any
    ) -> object:
        self.unbanned.append(chat_id)
        if chat_id in self.fail_ids:
            raise RuntimeError("transient boom")
        return True

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> object:
        self.logs.append(text)
        return object()


def _update(msg: _FakeMsg, admin: Any) -> Any:
    return SimpleNamespace(effective_message=msg, effective_user=admin)


def _ctx(bot: _FakeBot) -> Any:
    return SimpleNamespace(bot=bot)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ban: Any = "default",
    groups: Any = "default",
    deactivate: Any = "default",
) -> dict[str, list[str]]:
    """Stub locale, cfg, and DB seams; return call ledger."""
    calls: dict[str, list[str]] = {"deactivate": []}

    async def _locale(update: object) -> str:
        return "en-US"

    async def _get_active_ban(user_id: int) -> Any:
        if isinstance(ban, BaseException):
            raise ban
        if ban == "default":
            return {"ban_id": "ban1234567"}
        return ban

    async def _active_groups() -> Any:
        if isinstance(groups, BaseException):
            raise groups
        return groups

    async def _deactivate(user_id: int) -> int:
        calls["deactivate"].append("x")
        if isinstance(deactivate, BaseException):
            raise deactivate
        return 1

    monkeypatch.setattr(unban_flow, "locale_for_update", _locale)
    monkeypatch.setattr(
        unban_flow,
        "cfg",
        SimpleNamespace(main_group=-1, exec_group=-2, logs=(-3, None)),
    )
    monkeypatch.setattr(db.bans_db, "get_active_ban", _get_active_ban)
    monkeypatch.setattr(db.bans_db, "deactivate_all_active_bans", _deactivate)
    monkeypatch.setattr(db.groups_db, "active_groups", _active_groups)
    return calls


def _admin() -> Any:
    return SimpleNamespace(id=9, first_name="Admin")


def test_no_record_replies_without_touching_chats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, ban=None)
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_flow.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T"))
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.no_record", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_read_failure_replies_retry_and_skips_deactivate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, ban=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_flow.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T"))
    assert calls["deactivate"] == []
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.read_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_groups_failure_keeps_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, groups=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_flow.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T"))
    assert calls["deactivate"] == []
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.groups_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_deactivate_failure_aborts_before_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, deactivate=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_flow.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T"))
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.db_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_partial_fanout_names_missed_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 1, "title": "Gone"}, {"chat_id": -1, "title": ""}],
    )
    msg, bot = _FakeMsg(), _FakeBot(fail_ids={1})
    asyncio.run(unban_flow.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T"))
    assert "Gone" in msg.replies[-1]


def test_anonymous_admin_log_names_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_flow.execute_unban(_update(msg, None), _ctx(bot), 42, "T"))
    assert bot.logs and "anonymous admin" in bot.logs[-1]
