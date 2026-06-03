# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.start - welcome message text content and routing."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.start as start
from tcbot.modules.start import (
    _GROUP_START_TEXT,
    _PRIVATE_START_TEXT,
    cmd_start,
)

# ─────────────────────── Regex guards ──────────────────────────── #

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")

_BOTNAME = "TestBot"
_PRIVATE = _PRIVATE_START_TEXT.format(botname=_BOTNAME)
_GROUP = _GROUP_START_TEXT.format(botname=_BOTNAME)


# ───────────── private start text content ───────────────────────── #


def test_private_text_no_emoji() -> None:
    assert not _EMOJI_RE.search(_PRIVATE)


def test_private_text_no_em_dash() -> None:
    assert not _EMDASH_RE.search(_PRIVATE)


def test_private_text_contains_community_name() -> None:
    """cfg.community_name is injected at module load from conftest env."""
    assert "Test Federation" in _PRIVATE


def test_private_text_contains_botname() -> None:
    assert _BOTNAME in _PRIVATE


def test_private_text_contains_explore_prompt() -> None:
    assert "button" in _PRIVATE.lower() or "explore" in _PRIVATE.lower()


# ───────────── group start text content ─────────────────────────── #


def test_group_text_no_emoji() -> None:
    assert not _EMOJI_RE.search(_GROUP)


def test_group_text_no_em_dash() -> None:
    assert not _EMDASH_RE.search(_GROUP)


def test_group_text_mentions_help_command() -> None:
    assert "/help" in _GROUP


def test_group_text_contains_botname() -> None:
    assert _BOTNAME in _GROUP


def test_group_text_references_pm() -> None:
    assert "PM" in _GROUP or "pm" in _GROUP.lower() or "private" in _GROUP.lower()


# ───────────── cmd_start group routing ──────────────────────────── #


def _make_update(chat_type: str, text: str, uid: int) -> MagicMock:
    user = MagicMock()
    user.id = uid
    msg = AsyncMock()
    msg.text = text
    chat = MagicMock()
    chat.type = chat_type
    update = MagicMock()
    update.effective_user = user
    update.effective_message = msg
    update.effective_chat = chat
    return update


def _make_ctx(botname: str = "TestBot", username: str = "testbot") -> MagicMock:
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.first_name = botname
    ctx.bot.username = username
    return ctx


async def test_cmd_start_group_chat_sends_group_text() -> None:
    """Group context must send the group variant with PM link button."""
    update = _make_update("supergroup", "/start", uid=5001)
    ctx = _make_ctx()
    await cmd_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    call_text: str = update.effective_message.reply_text.call_args[0][0]
    assert "/help" in call_text


async def test_cmd_start_pm_no_arg_sends_private_text() -> None:
    """Private chat with no arg sends the main menu reply."""
    update = _make_update("private", "/start", uid=5002)
    ctx = _make_ctx()
    await cmd_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    call_text: str = update.effective_message.reply_text.call_args[0][0]
    assert "TestBot" in call_text


async def test_cmd_start_pm_about_arg_sends_about_msg() -> None:
    """Private chat with 'about' arg should send the about message."""
    update = _make_update("private", "/start about", uid=5003)
    ctx = _make_ctx()
    await cmd_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    call_text: str = update.effective_message.reply_text.call_args[0][0]
    # about message references the community name
    assert "Test Federation" in call_text


async def test_cmd_start_pm_appeal_arg_falls_through_to_main_menu() -> None:
    """Deep link args other than 'about' fall through to the main start menu."""
    update = _make_update("private", "/start appeal_999_1", uid=5004)
    ctx = _make_ctx()
    await cmd_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    call_text: str = update.effective_message.reply_text.call_args[0][0]
    # Should be private start text, not about
    assert "TestBot" in call_text


async def test_cmd_start_forum_type_treated_as_group() -> None:
    """Forum type is grouped with supergroup/group for routing."""
    update = _make_update("forum", "/start", uid=5005)
    ctx = _make_ctx()
    await cmd_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    call_text: str = update.effective_message.reply_text.call_args[0][0]
    assert "/help" in call_text


# ─────── Handler behavior: on_back_to_start / on_menu_groups callbacks ─── #

_on_back_to_start = start.on_back_to_start.__wrapped__.__wrapped__
_on_menu_groups = start.on_menu_groups.__wrapped__.__wrapped__
_on_menu_groups_details = start.on_menu_groups_details.__wrapped__.__wrapped__
_on_menu_groups_simple = start.on_menu_groups_simple.__wrapped__.__wrapped__


def _make_start_cb(data: str = "back_to_start") -> tuple:
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.first_name = "TestBot"
    return update, ctx


async def test_on_back_to_start_answers_and_edits_to_main_menu(monkeypatch) -> None:
    update, ctx = _make_start_cb("back_to_start")
    kb_mock = MagicMock()
    monkeypatch.setattr(
        start.keyboards, "main_menu_kb", MagicMock(return_value=kb_mock)
    )
    await _on_back_to_start(update, ctx)
    q = update.callback_query
    q.answer.assert_awaited_once()
    q.edit_message_text.assert_awaited_once()
    call_kwargs = q.edit_message_text.call_args[1]
    assert call_kwargs.get("reply_markup") is kb_mock


async def test_on_menu_groups_no_groups_edits_empty_message(monkeypatch) -> None:
    update, ctx = _make_start_cb("menu_groups")
    monkeypatch.setattr(start.db.groups_db, "active_groups", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        start.keyboards, "back_to_start_kb", MagicMock(return_value=None)
    )
    await _on_menu_groups(update, ctx)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "No groups" in update.callback_query.edit_message_text.call_args[0][0]


async def test_on_menu_groups_details_renders_with_detailed_true(monkeypatch) -> None:
    update, ctx = _make_start_cb("menu_groups_details")
    groups = [{"chat_id": -100, "title": "G1", "is_active": True}]
    monkeypatch.setattr(
        start.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    kb_mock = MagicMock()
    monkeypatch.setattr(
        start.keyboards, "groups_menu_kb", MagicMock(return_value=kb_mock)
    )
    await _on_menu_groups_details(update, ctx)
    update.callback_query.edit_message_text.assert_awaited_once()
    call_kwargs = update.callback_query.edit_message_text.call_args[1]
    assert call_kwargs.get("reply_markup") is kb_mock
    start.keyboards.groups_menu_kb.assert_called_once_with(True)


async def test_on_menu_groups_simple_renders_with_detailed_false(monkeypatch) -> None:
    update, ctx = _make_start_cb("menu_groups_simple")
    groups = [{"chat_id": -100, "title": "G1", "is_active": True}]
    monkeypatch.setattr(
        start.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )
    kb_mock = MagicMock()
    monkeypatch.setattr(
        start.keyboards, "groups_menu_kb", MagicMock(return_value=kb_mock)
    )
    await _on_menu_groups_simple(update, ctx)
    update.callback_query.edit_message_text.assert_awaited_once()
    start.keyboards.groups_menu_kb.assert_called_once_with(False)
