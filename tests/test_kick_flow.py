# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for the kick executor: happy path, ban failure, and log-send failure."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.modules.helper.workflows import kicking_flow

# ─────────────────────── Shared test helpers ────────────────────── #


def _make_update(
    *,
    chat_id: int = -100,
    chat_title: str = "Test Group",
    admin_id: int = 10,
    admin_fname: str = "Admin",
) -> SimpleNamespace:
    return SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        effective_chat=SimpleNamespace(id=chat_id, title=chat_title),
        effective_user=SimpleNamespace(id=admin_id, first_name=admin_fname),
    )


def _make_ctx(
    *,
    ban_side_effect=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(side_effect=ban_side_effect),
            unban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )


# ─────────────────────────── Test cases ─────────────────────────── #


async def test_execute_kick_happy_path(monkeypatch) -> None:
    """All four parallel operations succeed; user is kicked and reply is sent."""
    update = _make_update()
    ctx = _make_ctx()

    log_kick = AsyncMock()
    monkeypatch.setattr(kicking_flow.db.kicks_db, "log_kick", log_kick)
    monkeypatch.setattr(
        kicking_flow.parse_logmsg, "kick_log", Mock(return_value="kick log text")
    )

    await kicking_flow.execute_kick(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
        reason_text="flooding chat",
    )

    ctx.bot.ban_chat_member.assert_awaited_once_with(-100, 99)
    ctx.bot.unban_chat_member.assert_awaited_once()
    log_kick.assert_awaited_once()
    ctx.bot.send_message.assert_awaited_once()
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.await_args.args[0]
    assert "has been kicked" in reply_text
    assert "flooding chat" in reply_text


async def test_execute_kick_with_proof_desc_included_in_reply(monkeypatch) -> None:
    """Proof description is appended to the reply when provided."""
    update = _make_update()
    ctx = _make_ctx()

    monkeypatch.setattr(kicking_flow.db.kicks_db, "log_kick", AsyncMock())
    monkeypatch.setattr(kicking_flow.parse_logmsg, "kick_log", Mock(return_value="log"))

    await kicking_flow.execute_kick(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
        reason_text="spam",
        proof_desc="photo:https://t.me/c/1/2",
    )

    reply_text = update.effective_message.reply_text.await_args.args[0]
    assert "photo:https://t.me/c/1/2" in reply_text


async def test_execute_kick_ban_fails_sends_error_reply(monkeypatch) -> None:
    """When ban_chat_member raises, an error reply is sent and other ops are not called."""
    update = _make_update()
    ctx = _make_ctx(ban_side_effect=RuntimeError("no rights"))

    log_kick = AsyncMock()
    monkeypatch.setattr(kicking_flow.db.kicks_db, "log_kick", log_kick)

    await kicking_flow.execute_kick(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
        reason_text="spam",
    )

    update.effective_message.reply_text.assert_awaited_once()
    error_text = update.effective_message.reply_text.await_args.args[0]
    assert "Couldn't kick" in error_text

    log_kick.assert_not_awaited()
    ctx.bot.unban_chat_member.assert_not_awaited()
    ctx.bot.send_message.assert_not_awaited()


async def test_execute_kick_log_send_failure_still_reports_kick(monkeypatch) -> None:
    """A failure sending the audit log does not prevent the kick reply."""
    update = _make_update()
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            unban_chat_member=AsyncMock(),
            send_message=AsyncMock(side_effect=RuntimeError("log channel gone")),
        )
    )

    monkeypatch.setattr(kicking_flow.db.kicks_db, "log_kick", AsyncMock())
    monkeypatch.setattr(kicking_flow.parse_logmsg, "kick_log", Mock(return_value="log"))

    await kicking_flow.execute_kick(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
        reason_text="spam",
    )

    # * reply_text is called despite the log failure (gather return_exceptions=True)
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.await_args.args[0]
    assert "has been kicked" in reply_text
