# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.kicking - module metadata, help structure, and handler logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import ConversationHandler

import tcbot.modules.kicking as kicking
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.workflows.reason_flow import WAITING_PROOF, WAITING_REASON

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_kick() -> None:
    assert kicking.__module_name__ == "Kick"


def test_help_text_is_non_empty() -> None:
    assert isinstance(kicking.__help_text__, str)
    assert kicking.__help_text__.strip()


def test_help_text_mentions_group() -> None:
    assert "group" in kicking.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = kicking.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in kicking.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tckick() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "tckick" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tck_alias() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "/tck" in lookup["Commands & Aliases"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_contains_flow() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Flow" in keys


def test_help_sections_what_it_does_mentions_group_only() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "group" in lookup["What it does"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in kicking.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────── cmd_kick handler logic ────────────────────── #

# Access the unwrapped handler (bypass ratelimiter / basic_mod_only / log_execution).
_cmd_kick = kicking.cmd_kick.__wrapped__.__wrapped__.__wrapped__


def _make_kick_context(*, text: str = "/tckick @target reason") -> tuple:
    """Return (update, ctx) mocks ready for cmd_kick."""
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


async def test_cmd_kick_no_target_returns_end(monkeypatch) -> None:
    """When no target is resolved, handler ends the conversation."""
    monkeypatch.setattr(
        kicking.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_kick_context()
    result = await _cmd_kick(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_kick_refused_identity_returns_end(monkeypatch) -> None:
    """A refused identity (e.g. self-kick) sends the refusal and ends."""
    monkeypatch.setattr(
        kicking.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        kicking.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    monkeypatch.setattr(
        kicking, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_kick_context(text="/tckick 1 reason")
    result = await _cmd_kick(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_kick_inline_reason_returns_waiting_proof(monkeypatch) -> None:
    """When an inline reason is given, handler goes to proof step."""
    monkeypatch.setattr(
        kicking.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        kicking.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        kicking, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_kick_context(text="/tckick 42 spamming")
    result = await _cmd_kick(update, ctx)
    assert result == WAITING_PROOF
    assert ctx.user_data["kick_target_id"] == 42


async def test_cmd_kick_no_inline_reason_returns_waiting_reason(monkeypatch) -> None:
    """Without an inline reason, handler opens the reason-collection step."""
    monkeypatch.setattr(
        kicking.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        kicking.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        kicking, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_kick_context(text="/tckick 42")
    result = await _cmd_kick(update, ctx)
    assert result == WAITING_REASON


async def test_cmd_kick_executor_role_none_returns_end_silently(monkeypatch) -> None:
    """When resolve_and_check returns executor_role=None, handler exits without reply."""
    monkeypatch.setattr(
        kicking.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        kicking.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        kicking, "resolve_and_check", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_kick_context(text="/tckick 42 reason")
    result = await _cmd_kick(update, ctx)
    assert result == ConversationHandler.END


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(kicking.__handlers__, list)
    assert len(kicking.__handlers__) >= 1
