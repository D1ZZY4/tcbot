# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for the unban executor: no-active-ban guard and happy path."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.modules.helper.workflows import unban_flow

# ─────────────────────────── Test cases ─────────────────────────── #


async def test_execute_unban_no_active_ban_sends_notice(monkeypatch) -> None:
    """When there is no active ban, reply with 'has no active federation ban'."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            unban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )

    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_fname="Target",
    )

    msg.reply_text.assert_awaited_once()
    reply_text = msg.reply_text.await_args.args[0]
    assert "no active federation ban" in reply_text
    ctx.bot.unban_chat_member.assert_not_awaited()
    ctx.bot.send_message.assert_not_awaited()


async def test_execute_unban_happy_path(monkeypatch) -> None:
    """Deactivates the ban, unbans from all groups, and sends log + reply."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            # * fan_out is mocked; use Mock() so the list comprehension does not
            # * create unawaited coroutines that trigger PytestUnraisableExceptionWarning.
            unban_chat_member=Mock(),
            send_message=AsyncMock(),
        )
    )

    ban = {"ban_id": "ban0000001", "banned_user_id": 99}
    groups = [{"chat_id": -200}, {"chat_id": -300}]

    deactivate = AsyncMock()
    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )
    monkeypatch.setattr(unban_flow.db.bans_db, "deactivate_ban", deactivate)
    monkeypatch.setattr(
        unban_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(
        unban_flow.parse_logmsg, "unban_log", Mock(return_value="unban log text")
    )
    monkeypatch.setattr(unban_flow, "fan_out", AsyncMock(return_value=[None, None]))

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_fname="Target",
    )

    deactivate.assert_awaited_once_with("ban0000001")
    ctx.bot.send_message.assert_awaited_once()
    msg.reply_text.assert_awaited_once()
    reply_text = msg.reply_text.await_args.args[0]
    assert "has been unbanned" in reply_text
    assert "2/2" in reply_text


async def test_execute_unban_partial_group_failure_reported(monkeypatch) -> None:
    """When some group unbans fail, the reply shows the correct success ratio."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            # * fan_out is mocked; use Mock() so the list comprehension does not
            # * create unawaited coroutines that trigger PytestUnraisableExceptionWarning.
            unban_chat_member=Mock(),
            send_message=AsyncMock(),
        )
    )

    ban = {"ban_id": "ban0000002", "banned_user_id": 99}
    groups = [{"chat_id": -200}, {"chat_id": -300}, {"chat_id": -400}]

    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )
    monkeypatch.setattr(unban_flow.db.bans_db, "deactivate_ban", AsyncMock())
    monkeypatch.setattr(
        unban_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(unban_flow.parse_logmsg, "unban_log", Mock(return_value="log"))
    # * One group unban fails
    monkeypatch.setattr(
        unban_flow,
        "fan_out",
        AsyncMock(return_value=[None, RuntimeError("forbidden"), None]),
    )

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_fname="Target",
    )

    reply_text = msg.reply_text.await_args.args[0]
    assert "2/3" in reply_text


async def test_execute_unban_reply_includes_target_id(monkeypatch) -> None:
    """Happy-path reply must contain the target user ID."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(unban_chat_member=Mock(), send_message=AsyncMock())
    )

    ban = {"ban_id": "ban0000003", "banned_user_id": 77777}
    groups = [{"chat_id": -200}]

    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )
    monkeypatch.setattr(unban_flow.db.bans_db, "deactivate_ban", AsyncMock())
    monkeypatch.setattr(
        unban_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(unban_flow.parse_logmsg, "unban_log", Mock(return_value="log"))
    monkeypatch.setattr(unban_flow, "fan_out", AsyncMock(return_value=[None]))

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=77777,
        target_fname="Target",
    )

    reply_text = msg.reply_text.await_args.args[0]
    assert "77777" in reply_text


async def test_execute_unban_log_failure_does_not_prevent_reply(monkeypatch) -> None:
    """A failure sending the audit log must not suppress the reply to the admin."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            unban_chat_member=Mock(),
            send_message=AsyncMock(side_effect=RuntimeError("channel gone")),
        )
    )

    ban = {"ban_id": "ban0000004", "banned_user_id": 99}
    groups = [{"chat_id": -200}]

    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )
    monkeypatch.setattr(unban_flow.db.bans_db, "deactivate_ban", AsyncMock())
    monkeypatch.setattr(
        unban_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(unban_flow.parse_logmsg, "unban_log", Mock(return_value="log"))
    monkeypatch.setattr(unban_flow, "fan_out", AsyncMock(return_value=[None]))

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_fname="Target",
    )

    msg.reply_text.assert_awaited_once()
    reply_text = msg.reply_text.await_args.args[0]
    assert "has been unbanned" in reply_text


async def test_execute_unban_zero_groups_reply_shows_zero_of_zero(
    monkeypatch,
) -> None:
    """When no groups are connected, ratio in reply must be 0/0."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(unban_chat_member=Mock(), send_message=AsyncMock())
    )

    ban = {"ban_id": "ban0000005", "banned_user_id": 99}

    monkeypatch.setattr(
        unban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )
    monkeypatch.setattr(unban_flow.db.bans_db, "deactivate_ban", AsyncMock())
    monkeypatch.setattr(
        unban_flow.db.groups_db, "active_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(unban_flow.parse_logmsg, "unban_log", Mock(return_value="log"))
    monkeypatch.setattr(unban_flow, "fan_out", AsyncMock(return_value=[]))

    await unban_flow.execute_unban(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_fname="Target",
    )

    reply_text = msg.reply_text.await_args.args[0]
    assert "0/0" in reply_text
