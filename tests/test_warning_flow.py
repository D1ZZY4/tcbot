# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Regression tests for warning workflow edge cases."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.modules.helper.workflows import warning_flow


async def test_warn_limit_keeps_warns_when_auto_ban_fails(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(side_effect=RuntimeError("no rights")),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    # * Target holds no federation role — auto_demote should be skipped.
    monkeypatch.setattr(
        warning_flow, "get_effective_role", AsyncMock(return_value=None)
    )

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    clear_warns.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert "auto-ban failed" in msg.reply_text.await_args.args[0]


async def test_warn_limit_clears_warns_after_successful_auto_ban(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    monkeypatch.setattr(
        warning_flow, "get_effective_role", AsyncMock(return_value=None)
    )

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    clear_warns.assert_awaited_once_with(20, -100)
    msg.reply_text.assert_awaited_once()
    assert "has been banned" in msg.reply_text.await_args.args[0]


async def test_warn_limit_auto_demotes_role_holder_before_ban(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    auto_demote_mock = AsyncMock()
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    monkeypatch.setattr(
        warning_flow, "get_effective_role", AsyncMock(return_value="tester")
    )
    monkeypatch.setattr(warning_flow, "auto_demote", auto_demote_mock)

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    auto_demote_mock.assert_awaited_once()
    assert auto_demote_mock.await_args.args[1] == 20
    assert auto_demote_mock.await_args.args[3] == "tester"
    assert auto_demote_mock.await_args.args[6] == "ban"
