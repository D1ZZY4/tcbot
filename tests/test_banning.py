# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.banning - module metadata, help structure, and handler logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import ConversationHandler

import tcbot.modules.banning as banning
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.workflows.ban_flow import WAITING_PROOF

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_ban() -> None:
    assert banning.__module_name__ == "Ban"


def test_help_text_is_non_empty() -> None:
    assert isinstance(banning.__help_text__, str)
    assert banning.__help_text__.strip()


def test_help_text_mentions_ban() -> None:
    assert "ban" in banning.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = banning.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in banning.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in banning.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in banning.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcban() -> None:
    lookup = dict(banning.__help_sections__)
    assert "tcban" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcb_alias() -> None:
    lookup = dict(banning.__help_sections__)
    assert "/tcb" in lookup["Commands & Aliases"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in banning.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_what_it_does_mentions_federation() -> None:
    lookup = dict(banning.__help_sections__)
    assert "federation" in lookup["What it does"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in banning.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in banning.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(banning.__handlers__, list)
    assert len(banning.__handlers__) >= 1


# ─────────────────── cmd_ban_start handler logic ─────────────────── #

# Access the unwrapped handler (bypass ratelimiter / mod_only / log_execution).
_cmd_ban_start = banning.cmd_ban_start.__wrapped__.__wrapped__.__wrapped__


def _make_ban_context(*, text: str = "/tcban @target reason") -> tuple:
    """Return (update, ctx) mocks ready for cmd_ban_start."""
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


async def test_cmd_ban_start_no_target_returns_end(monkeypatch) -> None:
    """When extract_target resolves nothing, handler ends the conversation."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_ban_context()
    result = await _cmd_ban_start(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_ban_start_no_reason_returns_end(monkeypatch) -> None:
    """When no reason is provided after resolving a target, handler ends."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    update, ctx = _make_ban_context(text="/tcban 42")
    result = await _cmd_ban_start(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_ban_start_refused_identity_returns_end(monkeypatch) -> None:
    """A refused identity (e.g. self-ban) sends the refusal text and ends."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        banning.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    monkeypatch.setattr(
        banning, "resolve_and_check", AsyncMock(return_value=("developer", None))
    )
    update, ctx = _make_ban_context(text="/tcban 1 reason here")
    update.effective_user.id = 1
    result = await _cmd_ban_start(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_ban_start_executor_role_none_returns_end_silently(
    monkeypatch,
) -> None:
    """When resolve_and_check returns executor_role=None, handler exits silently."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(99, "User"))
    )
    monkeypatch.setattr(
        banning.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 99, "User", None)),
    )
    monkeypatch.setattr(
        banning, "resolve_and_check", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_ban_context(text="/tcban 99 reason here")
    result = await _cmd_ban_start(update, ctx)
    assert result == ConversationHandler.END


async def test_cmd_ban_start_valid_stores_user_data_and_returns_waiting_proof(
    monkeypatch,
) -> None:
    """Happy path: stores ban metadata in user_data and returns WAITING_PROOF."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        banning.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        banning, "resolve_and_check", AsyncMock(return_value=("developer", None))
    )
    update, ctx = _make_ban_context(text="/tcban 42 spamming in groups")
    result = await _cmd_ban_start(update, ctx)
    assert result == WAITING_PROOF
    assert ctx.user_data["ban_target_id"] == 42
    assert ctx.user_data["ban_reason"] == "spamming in groups"


async def test_cmd_ban_start_target_with_role_triggers_demote(monkeypatch) -> None:
    """When target holds a DB role, Demote.execute is called before the proof step."""
    monkeypatch.setattr(
        banning.extraction, "extract_target", AsyncMock(return_value=(42, "StaffUser"))
    )
    # Identity kind stays "user" — the target is a regular Telegram user.
    # Their *DB role* ("tester") is returned separately by resolve_and_check.
    monkeypatch.setattr(
        banning.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "StaffUser", None)),
    )
    monkeypatch.setattr(
        banning, "resolve_and_check", AsyncMock(return_value=("developer", "tester"))
    )
    demote_mock = AsyncMock()
    monkeypatch.setattr(banning.Demote, "execute", demote_mock)
    update, ctx = _make_ban_context(text="/tcban 42 reason here")
    result = await _cmd_ban_start(update, ctx)
    assert result == WAITING_PROOF
    demote_mock.assert_called_once()
