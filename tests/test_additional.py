# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.additional - __additional_msg__ content and handler."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

from tcbot.modules.additional import __additional_msg__, on_additional_menu

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")


# ─────────────────── message content ───────────────────────────── #


def test_additional_msg_no_emoji() -> None:
    assert not _EMOJI_RE.search(__additional_msg__)


def test_additional_msg_no_em_dash() -> None:
    assert not _EMDASH_RE.search(__additional_msg__)


def test_additional_msg_mentions_community_name() -> None:
    assert "Test Federation" in __additional_msg__


def test_additional_msg_non_empty() -> None:
    assert __additional_msg__ and __additional_msg__.strip()


def test_additional_msg_mentions_buttons() -> None:
    """Message should hint at the buttons below."""
    assert "button" in __additional_msg__.lower()


# ──────────────── callback handler wiring ──────────────────────── #


async def test_on_additional_menu_answers_and_edits() -> None:
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_additional_menu(update, ctx)

    q.answer.assert_called_once()
    q.edit_message_text.assert_called_once()
    call_text: str = q.edit_message_text.call_args[0][0]
    assert "Test Federation" in call_text


async def test_on_additional_menu_html_parse_mode() -> None:
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()

    await on_additional_menu(update, ctx)

    kwargs = q.edit_message_text.call_args[1]
    assert kwargs.get("parse_mode") == "HTML"
