# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.warnings - module metadata, help structure, and handler logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import ConversationHandler

import tcbot.modules.warnings as warnings
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.workflows.reason_flow import WAITING_PROOF, WAITING_REASON

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_warnings() -> None:
    assert warnings.__module_name__ == "Warnings"


def test_help_text_is_non_empty() -> None:
    assert isinstance(warnings.__help_text__, str)
    assert warnings.__help_text__.strip()


def test_help_text_mentions_warn() -> None:
    assert "warn" in warnings.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = warnings.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in warnings.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcwarn() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "tcwarn" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunwarn() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "tcunwarn" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_warns() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "warns" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_resetwarns() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "resetwarns" in lookup["Commands & Aliases"]


def test_help_sections_contains_flow() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Flow (/tcwarn)" in keys


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_what_it_does_mentions_per_group() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "per-group" in lookup["What it does"].lower()


def test_help_sections_who_can_use_distinguishes_roles() -> None:
    lookup = dict(warnings.__help_sections__)
    who = lookup["Who can use"]
    assert "Tester" in who
    assert "anyone" in who.lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in warnings.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert len(keys) == len(set(keys))


# ──────────────────── cmd_warn_entry handler logic ───────────────── #

# Access the unwrapped handler (bypass ratelimiter / basic_mod_only / log_execution).
_cmd_warn_entry = warnings.cmd_warn_entry.__wrapped__.__wrapped__.__wrapped__


def _make_warn_context(*, text: str = "/tcwarn @target reason") -> tuple:
    """Return (update, ctx) mocks ready for cmd_warn_entry."""
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


async def test_cmd_warn_entry_no_target_returns_end(monkeypatch) -> None:
    """When no target is resolved, handler ends the conversation."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_warn_context()
    result = await _cmd_warn_entry(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_warn_entry_refused_identity_returns_end(monkeypatch) -> None:
    """A refused identity (e.g. self-warn) sends the refusal and ends."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    monkeypatch.setattr(
        warnings, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_warn_context(text="/tcwarn 1 reason")
    result = await _cmd_warn_entry(update, ctx)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_warn_entry_executor_role_none_returns_end_silently(
    monkeypatch,
) -> None:
    """When resolve_and_check returns executor_role=None, handler exits without reply."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        warnings, "resolve_and_check", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_warn_context(text="/tcwarn 42 reason")
    result = await _cmd_warn_entry(update, ctx)
    assert result == ConversationHandler.END


async def test_cmd_warn_entry_with_inline_reason_returns_waiting_proof(
    monkeypatch,
) -> None:
    """When target + inline reason are given, handler opens proof step."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        warnings, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_warn_context(text="/tcwarn 42 spamming")
    result = await _cmd_warn_entry(update, ctx)
    assert result == WAITING_PROOF
    assert ctx.user_data["warn_target_id"] == 42
    assert ctx.user_data["warn_reason"] == "spamming"


async def test_cmd_warn_entry_no_inline_reason_returns_waiting_reason(
    monkeypatch,
) -> None:
    """Without an inline reason, handler opens the reason-collection step."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    monkeypatch.setattr(
        warnings, "resolve_and_check", AsyncMock(return_value=("tester", None))
    )
    update, ctx = _make_warn_context(text="/tcwarn 42")
    result = await _cmd_warn_entry(update, ctx)
    assert result == WAITING_REASON


# ─────────────────── cmd_unwarn handler logic ────────────────────── #

# Access the unwrapped handler (bypass ratelimiter / basic_mod_only / log_execution).
_cmd_unwarn = warnings.cmd_unwarn.__wrapped__.__wrapped__.__wrapped__

# cmd_warnlist has only 2 decorators: ratelimiter + log_execution.
_cmd_warnlist = warnings.cmd_warnlist.__wrapped__.__wrapped__

# cmd_resetwarns has 3 decorators: ratelimiter + basic_mod_only + log_execution.
_cmd_resetwarns = warnings.cmd_resetwarns.__wrapped__.__wrapped__.__wrapped__


def _make_unwarn_context(*, text: str = "/tcunwarn @target") -> tuple:
    """Return (update, ctx) mocks ready for cmd_unwarn and similar handlers."""
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


async def test_cmd_unwarn_no_target_returns_early(monkeypatch) -> None:
    """When no target is resolved, handler replies and returns early."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_unwarn_context()
    await _cmd_unwarn(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unwarn_refused_identity_returns_early(monkeypatch) -> None:
    """A refused identity sends the refusal message and returns."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    update, ctx = _make_unwarn_context(text="/tcunwarn 1")
    await _cmd_unwarn(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_unwarn_valid_target_calls_execute_unwarn(monkeypatch) -> None:
    """With a valid target and no refusal, execute_unwarn is delegated to."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(warnings, "execute_unwarn", execute_mock)
    update, ctx = _make_unwarn_context(text="/tcunwarn 42")
    await _cmd_unwarn(update, ctx)
    execute_mock.assert_called_once()
    update.effective_message.reply_text.assert_not_called()


# ─────────────────── cmd_warnlist handler logic ──────────────────── #


async def test_cmd_warnlist_no_target_returns_early(monkeypatch) -> None:
    """When no target is resolved, handler replies and returns early."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_unwarn_context(text="/warns")
    await _cmd_warnlist(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_warnlist_valid_target_calls_execute_warnlist(monkeypatch) -> None:
    """With a valid target, execute_warnlist is delegated to."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(warnings, "execute_warnlist", execute_mock)
    update, ctx = _make_unwarn_context(text="/warns 42")
    await _cmd_warnlist(update, ctx)
    execute_mock.assert_called_once()


# ──────────────── cmd_resetwarns handler logic ───────────────────── #


async def test_cmd_resetwarns_no_target_returns_early(monkeypatch) -> None:
    """When no target is resolved, handler replies and returns early."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(None, None))
    )
    update, ctx = _make_unwarn_context(text="/resetwarns")
    await _cmd_resetwarns(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_resetwarns_refused_identity_returns_early(monkeypatch) -> None:
    """A refused identity sends the refusal message and returns."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(1, "Me"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("self", 1, "Me", None)),
    )
    update, ctx = _make_unwarn_context(text="/resetwarns 1")
    await _cmd_resetwarns(update, ctx)
    update.effective_message.reply_text.assert_called_once()


async def test_cmd_resetwarns_valid_target_calls_execute_resetwarns(
    monkeypatch,
) -> None:
    """With a valid target and no refusal, execute_resetwarns is called."""
    monkeypatch.setattr(
        warnings.extraction, "extract_target", AsyncMock(return_value=(42, "Target"))
    )
    monkeypatch.setattr(
        warnings.identity,
        "classify",
        AsyncMock(return_value=Identity("user", 42, "Target", None)),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(warnings, "execute_resetwarns", execute_mock)
    update, ctx = _make_unwarn_context(text="/resetwarns 42")
    await _cmd_resetwarns(update, ctx)
    execute_mock.assert_called_once()
    update.effective_message.reply_text.assert_not_called()


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(warnings.__handlers__, list)
    assert len(warnings.__handlers__) >= 2
