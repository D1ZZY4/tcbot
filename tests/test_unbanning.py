# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.unbanning - module metadata, help structure, and handler logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.unbanning as unbanning
from tcbot.modules.helper.identity import Identity

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_unban() -> None:
    assert unbanning.__module_name__ == "Unban"


def test_help_text_is_non_empty() -> None:
    assert isinstance(unbanning.__help_text__, str)
    assert unbanning.__help_text__.strip()


def test_help_text_mentions_federation_ban() -> None:
    assert "federation ban" in unbanning.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = unbanning.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in unbanning.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcunban() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "tcunban" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunb_alias() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "tcunb" in lookup["Commands & Aliases"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_what_it_does_mentions_all_groups() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "all connected groups" in lookup["What it does"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in unbanning.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(unbanning.__handlers__, list)
    assert len(unbanning.__handlers__) >= 1


# ────────────────────── cmd_unban handler logic ──────────────────── #

# Access the unwrapped handler (bypass ratelimiter / mod_only / log_execution).
_cmd_unban = unbanning.cmd_unban.__wrapped__.__wrapped__.__wrapped__


def _make_unban_context(*, text: str = "/tcunban @target") -> tuple:
    """Return (update, ctx) mocks ready for cmd_unban."""
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


async def test_cmd_unban_no_target_returns_early(monkeypatch) -> None:
    """When no target is resolved, handler replies and returns without unbanning."""
    monkeypatch.setattr(
        unbanning.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_unban_context()
    await _cmd_unban(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unban_refused_identity_returns_early(monkeypatch) -> None:
    """A refused identity (e.g. self-unban) sends the refusal text and returns."""
    monkeypatch.setattr(
        unbanning.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        unbanning.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    update, ctx = _make_unban_context(text="/tcunban 1")
    await _cmd_unban(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unban_valid_target_calls_execute_unban(monkeypatch) -> None:
    """With a valid target and no refusal, execute_unban is delegated to."""
    monkeypatch.setattr(
        unbanning.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        unbanning.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(unbanning, "execute_unban", execute_mock)
    update, ctx = _make_unban_context(text="/tcunban 42")
    await _cmd_unban(update, ctx)
    execute_mock.assert_called_once_with(update, ctx, 42, "Target")
    update.effective_message.reply_text.assert_not_called()
