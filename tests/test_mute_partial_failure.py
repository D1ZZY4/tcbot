# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute two-write commit: an audit failure rolls back the enforcement record."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import muting_flow
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t


class _FakeBot:
    """Bot double recording edits and restrictions, succeeding every call."""

    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.restricts: list[dict[str, Any]] = []

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> object:
        self.edits.append({"args": args, "kwargs": kwargs})
        return object()

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        self.restricts.append({"args": args, "kwargs": kwargs})
        return True

    async def send_message(self, *args: Any, **kwargs: Any) -> object:
        return object()


class _FakeChat:
    id = 22


class _FakeUpdate:
    """Update double exposing effective_chat like the mute executor needs."""

    def __init__(self) -> None:
        self.effective_chat = _FakeChat()


def _meta() -> dict[str, Any]:
    return {
        "mute_target_id": 33,
        "mute_admin_id": 1,
        "mute_target_fname": "Target",
        "mute_reason": "spam",
        "mute_duration": timedelta(hours=1),
        "mute_proof_msgs": None,
        "mute_prompt_chat": 22,
        "mute_prompt_id": 44,
    }


@pytest.fixture
def _mute_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub locale, group fetch, and demote re-check so no database is touched."""

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _no_groups() -> list[dict[str, Any]]:
        return []

    async def _no_redemote(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(muting_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.groups_db, "active_groups", _no_groups)
    monkeypatch.setattr(Demote, "redemote_before_fanout", _no_redemote)


def _run(bot: _FakeBot) -> None:
    asyncio.run(
        muting_flow._execute_mute(
            bot,  # type: ignore[arg-type]
            _FakeUpdate(),  # type: ignore[arg-type]
            _meta(),  # type: ignore[arg-type]
        )
    )


def _expected_db_fail() -> str:
    return t(
        "muting.note.db_fail",
        "en-US",
        user=Safe(user_ref(33, "Target")),
    )


def test_active_write_fails_after_audit_not_written(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_calls: list[tuple[Any, ...]] = []

    async def _set_active(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("active write down")

    async def _log(*args: Any, **kwargs: Any) -> None:
        log_calls.append((args, kwargs))

    monkeypatch.setattr(db.mutes_db, "set_active_mute", _set_active)
    monkeypatch.setattr(db.mutes_db, "log_mute", _log)

    bot = _FakeBot()
    _run(bot)

    assert log_calls == []
    assert bot.restricts == []
    assert len(bot.edits) == 1
    assert bot.edits[0]["kwargs"]["chat_id"] == 22
    assert bot.edits[0]["kwargs"]["message_id"] == 44
    assert bot.edits[0]["args"][0] == _expected_db_fail()


def test_audit_fail_undoes_active_record(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[int] = []

    async def _set_active(*args: Any, **kwargs: Any) -> None:
        return None

    async def _log(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit write down")

    async def _clear_active(user_id: int) -> None:
        deleted.append(user_id)

    monkeypatch.setattr(db.mutes_db, "set_active_mute", _set_active)
    monkeypatch.setattr(db.mutes_db, "log_mute", _log)
    monkeypatch.setattr(db.mutes_db, "clear_active_mute", _clear_active)

    bot = _FakeBot()
    _run(bot)

    assert deleted == [33]
    assert bot.restricts == []
    assert len(bot.edits) == 1
    assert bot.edits[0]["kwargs"]["chat_id"] == 22


def test_audit_fail_undo_failure_logged_not_raised(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _set_active(*args: Any, **kwargs: Any) -> None:
        return None

    async def _log(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit write down")

    async def _clear_active(user_id: int) -> None:
        raise RuntimeError("undo down")

    monkeypatch.setattr(db.mutes_db, "set_active_mute", _set_active)
    monkeypatch.setattr(db.mutes_db, "log_mute", _log)
    monkeypatch.setattr(db.mutes_db, "clear_active_mute", _clear_active)

    bot = _FakeBot()
    _run(bot)  # must not raise

    assert bot.restricts == []
    assert len(bot.edits) == 1
    assert bot.edits[0]["kwargs"]["chat_id"] == 22
