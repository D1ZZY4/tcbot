# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for mute/unmute executors and duration helpers."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.modules.helper.workflows import muting_flow

# ──────────────────────── Duration helpers ──────────────────────── #


def test_parse_duration_seconds() -> None:
    assert muting_flow.parse_duration("30s") == timedelta(seconds=30)


def test_parse_duration_minutes() -> None:
    assert muting_flow.parse_duration("5m") == timedelta(minutes=5)


def test_parse_duration_hours() -> None:
    assert muting_flow.parse_duration("2h") == timedelta(hours=2)


def test_parse_duration_days() -> None:
    assert muting_flow.parse_duration("7d") == timedelta(days=7)


def test_parse_duration_weeks() -> None:
    assert muting_flow.parse_duration("1w") == timedelta(weeks=1)


def test_parse_duration_months() -> None:
    assert muting_flow.parse_duration("3mo") == timedelta(days=90)


def test_parse_duration_years() -> None:
    assert muting_flow.parse_duration("2ye") == timedelta(days=730)


def test_parse_duration_case_insensitive() -> None:
    assert muting_flow.parse_duration("1D") == timedelta(days=1)
    assert muting_flow.parse_duration("1MO") == timedelta(days=30)


def test_parse_duration_invalid_returns_none() -> None:
    assert muting_flow.parse_duration("bananas") is None
    assert muting_flow.parse_duration("") is None
    assert muting_flow.parse_duration("5x") is None
    assert muting_flow.parse_duration("0d") == timedelta(days=0)


# ────────────────────────── fmt_duration ────────────────────────── #


def test_fmt_duration_none_returns_permanently() -> None:
    assert muting_flow.fmt_duration(None) == "permanently"


def test_fmt_duration_under_minute() -> None:
    assert muting_flow.fmt_duration(timedelta(seconds=45)) == "45s"


def test_fmt_duration_minutes() -> None:
    assert muting_flow.fmt_duration(timedelta(minutes=30)) == "30m"


def test_fmt_duration_hours() -> None:
    assert muting_flow.fmt_duration(timedelta(hours=3)) == "3h"


def test_fmt_duration_days() -> None:
    assert muting_flow.fmt_duration(timedelta(days=3)) == "3d"


def test_fmt_duration_weeks() -> None:
    assert muting_flow.fmt_duration(timedelta(days=14)) == "2w"


def test_fmt_duration_months() -> None:
    assert muting_flow.fmt_duration(timedelta(days=60)) == "2mo"


def test_fmt_duration_years() -> None:
    assert muting_flow.fmt_duration(timedelta(days=730)) == "2ye"


# ──────────────────────── Mute executor ─────────────────────────── #


async def test_execute_mute_happy_path(monkeypatch) -> None:
    """All groups are muted, DB logged, log posted, and prompt edited to summary."""
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
        # * fan_out is mocked; use Mock() so the list comprehension does not
        # * create unawaited coroutines that trigger PytestUnraisableExceptionWarning.
        restrict_chat_member=Mock(),
    )

    groups = [{"chat_id": -200}, {"chat_id": -300}]
    log_mute = AsyncMock()
    monkeypatch.setattr(
        muting_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(muting_flow.db.mutes_db, "log_mute", log_mute)
    monkeypatch.setattr(
        muting_flow.parse_logmsg, "mute_log", Mock(return_value="mute log text")
    )
    monkeypatch.setattr(muting_flow, "fan_out", AsyncMock(return_value=[None, None]))

    meta = {
        "mute_target_id": 99,
        "mute_target_fname": "Target",
        "mute_reason": "flooding",
        "mute_admin_id": 10,
        "mute_admin_fname": "Admin",
        "mute_duration": timedelta(hours=1),
        "mute_proof_desc": None,
        "mute_prompt_chat": -100,
        "mute_prompt_id": 42,
    }

    await muting_flow._execute_mute(bot, cast(Update, update), meta)

    log_mute.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    bot.edit_message_text.assert_awaited_once()
    edited_text = bot.edit_message_text.await_args.kwargs.get(
        "text",
        bot.edit_message_text.await_args.args[0]
        if bot.edit_message_text.await_args.args
        else "",
    )
    assert "has been muted" in edited_text
    assert "flooding" in edited_text


async def test_execute_mute_with_proof_desc(monkeypatch) -> None:
    """Proof description is included in the mute summary when provided."""
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    monkeypatch.setattr(
        muting_flow.db.groups_db, "active_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(muting_flow.db.mutes_db, "log_mute", AsyncMock())
    monkeypatch.setattr(muting_flow.parse_logmsg, "mute_log", Mock(return_value="log"))
    monkeypatch.setattr(muting_flow, "fan_out", AsyncMock(return_value=[]))

    meta = {
        "mute_target_id": 99,
        "mute_target_fname": "Target",
        "mute_reason": "spam",
        "mute_admin_id": 10,
        "mute_admin_fname": "Admin",
        "mute_duration": None,
        "mute_proof_desc": "photo:https://t.me/c/1/2",
        "mute_prompt_chat": -100,
        "mute_prompt_id": 42,
    }

    await muting_flow._execute_mute(bot, cast(Update, update), meta)

    edited_text = bot.edit_message_text.await_args.kwargs.get(
        "text",
        bot.edit_message_text.await_args.args[0]
        if bot.edit_message_text.await_args.args
        else "",
    )
    assert "photo:https://t.me/c/1/2" in edited_text


# ─────────────────────── Unmute executor ────────────────────────── #


async def test_execute_unmute_happy_path(monkeypatch) -> None:
    """Unmute restores permissions across all groups and sends log + reply."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            # * fan_out is mocked; use Mock() so the list comprehension does not
            # * create unawaited coroutines that trigger PytestUnraisableExceptionWarning.
            restrict_chat_member=Mock(),
            send_message=AsyncMock(),
        )
    )

    groups = [{"chat_id": -200}, {"chat_id": -300}]
    monkeypatch.setattr(
        muting_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(
        muting_flow.parse_logmsg, "unmute_log", Mock(return_value="unmute log text")
    )
    monkeypatch.setattr(muting_flow, "fan_out", AsyncMock(return_value=[None, None]))

    await muting_flow.execute_unmute(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
    )

    ctx.bot.send_message.assert_awaited_once()
    msg.reply_text.assert_awaited_once()
    reply_text = msg.reply_text.await_args.args[0]
    assert "has been unmuted" in reply_text
    assert "2/2" in reply_text


async def test_execute_unmute_partial_failure_reported_in_reply(monkeypatch) -> None:
    """When some groups fail, the reply shows the correct success ratio."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            # * fan_out is mocked; use Mock() so the list comprehension does not
            # * create unawaited coroutines that trigger PytestUnraisableExceptionWarning.
            restrict_chat_member=Mock(),
            send_message=AsyncMock(),
        )
    )

    groups = [{"chat_id": -200}, {"chat_id": -300}, {"chat_id": -400}]
    # * Two succeed, one fails
    monkeypatch.setattr(
        muting_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    monkeypatch.setattr(
        muting_flow.parse_logmsg, "unmute_log", Mock(return_value="log")
    )
    monkeypatch.setattr(
        muting_flow,
        "fan_out",
        AsyncMock(return_value=[None, RuntimeError("forbidden"), None]),
    )

    await muting_flow.execute_unmute(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=99,
        target_name="Target",
    )

    reply_text = msg.reply_text.await_args.args[0]
    assert "2/3" in reply_text
