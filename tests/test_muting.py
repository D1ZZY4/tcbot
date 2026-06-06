# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.muting - module metadata, help structure, and handler logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import ConversationHandler

import tcbot.modules.muting as muting
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.workflows.reason_flow import WAITING_PROOF, WAITING_REASON

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_mute() -> None:
    assert muting.__module_name__ == "Mute"


def test_help_text_is_non_empty() -> None:
    assert isinstance(muting.__help_text__, str)
    assert muting.__help_text__.strip()


def test_help_text_mentions_mute() -> None:
    assert "mute" in muting.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = muting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in muting.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcmute() -> None:
    lookup = dict(muting.__help_sections__)
    assert "tcmute" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunmute() -> None:
    lookup = dict(muting.__help_sections__)
    assert "tcunmute" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcm_alias() -> None:
    lookup = dict(muting.__help_sections__)
    assert "/tcm" in lookup["Commands & Aliases"]


def test_help_sections_contains_time_format() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Time format" in keys


def test_help_sections_time_format_mentions_duration_units() -> None:
    lookup = dict(muting.__help_sections__)
    for unit_code in ("s", "m", "h", "d", "w"):
        assert unit_code in lookup["Time format"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_no_emdash() -> None:
    for _key, value in muting.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────── cmd_mute handler logic ────────────────────── #

# Access the unwrapped handler (bypass ratelimiter / basic_mod_only / log_execution).
_cmd_mute = muting.cmd_mute.__wrapped__.__wrapped__.__wrapped__


def _make_mute_context(*, text: str = "/tcmute @target reason") -> tuple:
    """Return (update, ctx) mocks ready for cmd_mute."""
    msg = AsyncMock()
    msg.text = text
    msg.chat = SimpleNamespace(id=100)
    msg.reply_text = AsyncMock(return_value=SimpleNamespace(message_id=1))
    admin = SimpleNamespace(id=1, first_name="Admin")
    update = MagicMock()
    update.effective_message = msg
    update.effective_user = admin
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.id = 9999
    ctx.user_data = {}
    return update, ctx


async def test_cmd_mute_no_target_returns_end(monkeypatch) -> None:
    """When no target is resolved, handler ends the conversation."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_mute_context()
    result = await _cmd_mute(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_mute_refused_identity_returns_end(monkeypatch) -> None:
    """A refused identity (e.g. self-mute) sends the refusal and ends."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    monkeypatch.setattr(
        muting, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_mute_context(text="/tcmute 1 reason")
    result = await _cmd_mute(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_mute_executor_role_none_returns_end_silently(monkeypatch) -> None:
    """When resolve_and_check returns executor_role=None, handler exits without reply."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        muting, "resolve_and_check", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_mute_context(text="/tcmute 42 reason")
    result = await _cmd_mute(update, ctx)
    assert result == ConversationHandler.END


async def test_cmd_mute_with_inline_reason_returns_waiting_proof(monkeypatch) -> None:
    """When target + inline reason are given (no duration), handler opens proof step."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        muting, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_mute_context(text="/tcmute 42 spamming")
    result = await _cmd_mute(update, ctx)
    assert result == WAITING_PROOF
    assert ctx.user_data["mute_target_id"] == 42
    assert ctx.user_data["mute_reason"] == "spamming"


async def test_cmd_mute_no_inline_reason_returns_waiting_reason(monkeypatch) -> None:
    """Without an inline reason, handler opens the reason-collection step."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        muting, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_mute_context(text="/tcmute 42")
    result = await _cmd_mute(update, ctx)
    assert result == WAITING_REASON


# ─────────────────── cmd_unmute handler logic ────────────────────── #

# Access the unwrapped handler (bypass ratelimiter / basic_mod_only / log_execution).
_cmd_unmute = muting.cmd_unmute.__wrapped__.__wrapped__.__wrapped__


def _make_unmute_context(*, text: str = "/tcunmute @target") -> tuple:
    """Return (update, ctx) mocks ready for cmd_unmute."""
    msg = AsyncMock()
    msg.text = text
    msg.chat = SimpleNamespace(id=100)
    msg.reply_text = AsyncMock(return_value=SimpleNamespace(message_id=1))
    admin = SimpleNamespace(id=1, first_name="Admin")
    update = MagicMock()
    update.effective_message = msg
    update.effective_user = admin
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.id = 9999
    ctx.user_data = {}
    return update, ctx


async def test_cmd_unmute_no_target_returns_early(monkeypatch) -> None:
    """When no target is resolved, handler replies and returns early."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_unmute_context()
    await _cmd_unmute(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unmute_refused_identity_returns_early(monkeypatch) -> None:
    """A refused identity (e.g. self-unmute) sends the refusal and returns."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    update, ctx = _make_unmute_context(text="/tcunmute 1")
    await _cmd_unmute(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unmute_valid_user_calls_execute_unmute(monkeypatch) -> None:
    """With a regular user target, execute_unmute is called without a staff notice."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(muting, "execute_unmute", execute_mock)
    update, ctx = _make_unmute_context(text="/tcunmute 42")
    await _cmd_unmute(update, ctx)
    execute_mock.assert_called_once()
    # No staff notice for a plain user target.
    update.effective_message.reply_text.assert_not_called()


async def test_cmd_unmute_staff_target_emits_notice_before_execute(
    monkeypatch,
) -> None:
    """When the target is a staff member, a notice is sent before executing unmute."""
    monkeypatch.setattr(
        muting.extraction, "extract_target", AsyncMock(return_value=(42, "Staff"))
    )
    monkeypatch.setattr(
        muting.identity,
        "classify",
        AsyncMock(return_value=Identity("tester", 42, "Staff", None)),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(muting, "execute_unmute", execute_mock)
    update, ctx = _make_unmute_context(text="/tcunmute 42")
    await _cmd_unmute(update, ctx)
    # The staff notice reply must precede the execute call.
    update.effective_message.reply_text.assert_called_once()
    execute_mock.assert_called_once()


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(muting.__handlers__, list)
    assert len(muting.__handlers__) >= 1
