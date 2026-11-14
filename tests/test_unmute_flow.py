# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""execute_unmute clears before announcing and fails closed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot import database as db
from tcbot.modules.helper.messages import replies
from tcbot.modules.helper.pipelines import mute_flow
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
    """Bot double recording unrestricts and log sends."""

    def __init__(self, fail_chats: set[int] | None = None) -> None:
        self.unrestricted: list[int] = []
        self.logs: list[str] = []
        self.fail_chats = fail_chats or set()

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, **kwargs: Any
    ) -> object:
        if chat_id in self.fail_chats:
            raise RuntimeError("flood wait")
        self.unrestricted.append(chat_id)
        return True

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> object:
        self.logs.append(text)
        return object()


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mute: Any = "default",
    groups: Any = "default",
    clear: Any = "default",
) -> dict[str, list[str]]:
    """Stub locale, cfg, and DB seams; return call ledger."""
    calls: dict[str, list[str]] = {"clear": []}

    async def _locale(update: object) -> str:
        return "en-US"

    async def _get_active_mute(user_id: int) -> Any:
        if isinstance(mute, BaseException):
            raise mute
        if mute == "default":
            return {"user_id": user_id}
        return mute

    async def _active_groups() -> Any:
        if isinstance(groups, BaseException):
            raise groups
        return groups

    async def _clear(user_id: int) -> None:
        calls["clear"].append("x")
        if isinstance(clear, BaseException):
            raise clear

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(
        mute_flow,
        "cfg",
        SimpleNamespace(main_group=-1, exec_group=-2, logs=(-3, None)),
    )
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _get_active_mute)
    monkeypatch.setattr(db.mutes_db, "clear_active_mute", _clear)
    monkeypatch.setattr(db.groups_db, "active_groups", _active_groups)
    return calls


def _update(msg: _FakeMsg) -> Any:
    admin = SimpleNamespace(id=9, first_name="Admin")
    return SimpleNamespace(effective_message=msg, effective_user=admin)


def _ctx(bot: _FakeBot) -> Any:
    return cast("Any", SimpleNamespace(bot=bot))


def _retry() -> str:
    return replies.err_db_retry("en-US", plain=True)


def test_no_mute_replies_without_touching_chats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, mute=None, groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert bot.unrestricted == []
    assert msg.replies == [
        t("muting.note.no_mute", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_read_failure_replies_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, mute=RuntimeError("db down"), groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert bot.unrestricted == []
    assert msg.replies == [_retry()]


def test_groups_failure_replies_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch, groups=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["clear"] == []
    assert msg.replies == [_retry()]


def test_clear_failure_aborts_without_success_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        clear=RuntimeError("db down"),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert msg.replies == [_retry()]


def test_happy_path_clears_then_announces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, groups=[{"chat_id": 5, "title": "G"}])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert bot.unrestricted != []
    assert len(msg.replies) == 1
    assert msg.replies[0] != _retry()


# * The two failure shapes are separate notices: a partial unmute restored
# * most groups, so telling the moderator that the user could not be
# * unmuted in any group is wrong.


def _two_groups() -> list[dict[str, Any]]:
    """Return a group list that already carries the primary group."""
    return [{"chat_id": 5, "title": "G"}, {"chat_id": -1, "title": "P"}]


def test_partial_unmute_reports_the_split_and_keeps_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, groups=_two_groups())
    msg, bot = _FakeMsg(), _FakeBot(fail_chats={5})
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["clear"] == []
    assert len(msg.replies) == 1
    applied = replies.applied_summary(
        "en-US",
        "muting.applied",
        total=2,
        failed=1,
        transient=[({"chat_id": 5, "title": "G"}, RuntimeError("flood wait"))],
    )
    assert msg.replies == [
        t(
            "muting.note.unmute_partial",
            "en-US",
            user=Safe(user_ref(42, "T")),
            applied=Safe(applied),
        )
    ]
    # * The split is named, so the moderator sees that one group was
    # * restored and one failed.
    assert "1/2" in msg.replies[0]


def test_total_unmute_failure_reports_every_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, groups=_two_groups())
    msg, bot = _FakeMsg(), _FakeBot(fail_chats={5, -1})
    asyncio.run(mute_flow.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["clear"] == []
    assert len(msg.replies) == 1
    applied = replies.applied_summary(
        "en-US",
        "muting.applied",
        total=2,
        failed=2,
        transient=[
            ({"chat_id": 5, "title": "G"}, RuntimeError("flood wait")),
            ({"chat_id": -1, "title": "P"}, RuntimeError("flood wait")),
        ],
    )
    assert msg.replies == [
        t(
            "muting.note.unmute_failed",
            "en-US",
            user=Safe(user_ref(42, "T")),
            applied=Safe(applied),
        )
    ]
    assert "2/2" in msg.replies[0]
