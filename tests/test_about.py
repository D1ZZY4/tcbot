# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.about - __about_msg__ content and callback handler."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

from tcbot.modules.about import __about_msg__, on_about_menu

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")


# ─────────────────── message content ───────────────────────────── #


def test_about_msg_no_emoji() -> None:
    assert not _EMOJI_RE.search(__about_msg__)


def test_about_msg_no_em_dash() -> None:
    assert not _EMDASH_RE.search(__about_msg__)


def test_about_msg_mentions_community_name() -> None:
    assert "Test Federation" in __about_msg__


def test_about_msg_non_empty() -> None:
    assert __about_msg__ and __about_msg__.strip()


def test_about_msg_has_html_bold_tag() -> None:
    """About message uses HTML bold for section headers."""
    assert "<b>" in __about_msg__


def test_about_msg_contains_history_section() -> None:
    assert "History" in __about_msg__ or "Established" in __about_msg__


def test_about_msg_mentions_independence() -> None:
    """Must clarify this is an independent community, not an official entity."""
    low = __about_msg__.lower()
    assert "independent" in low or "not an official" in low or "unofficial" in low


# ──────────────── callback handler wiring ──────────────────────── #


async def test_on_about_menu_answers_callback_and_edits_message() -> None:
    """Handler must answer the query and edit the message in the same call."""
    q = AsyncMock()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_about_menu(update, ctx)

    q.answer.assert_called_once()
    q.edit_message_text.assert_called_once()
    call_text: str = q.edit_message_text.call_args[0][0]
    assert "Test Federation" in call_text


async def test_on_about_menu_passes_html_parse_mode() -> None:
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_about_menu(update, ctx)

    kwargs = q.edit_message_text.call_args[1]
    assert kwargs.get("parse_mode") == "HTML"


def test_about_msg_is_string_type() -> None:
    assert isinstance(__about_msg__, str)


async def test_on_about_menu_edit_text_equals_about_msg() -> None:
    """The text sent to the user must be exactly __about_msg__."""
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_about_menu(update, ctx)

    call_text: str = q.edit_message_text.call_args[0][0]
    assert call_text == __about_msg__


async def test_on_about_menu_has_reply_markup_kwarg() -> None:
    """edit_message_text must receive a reply_markup keyword argument."""
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_about_menu(update, ctx)

    kwargs = q.edit_message_text.call_args[1]
    assert "reply_markup" in kwargs
