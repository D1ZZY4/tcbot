# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.privacy - privacy message content and callbacks."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

# Access private constants through the module
import tcbot.modules.privacy as _priv_mod
from tcbot.modules.privacy import on_privacy_menu, on_privacy_policy_menu

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")

_BOTNAME = "TestBot"
_PRIVACY_MSG = _priv_mod._PRIVACY_MSG.format(botname=_BOTNAME)
_POLICY_MSG = _priv_mod._PRIVACY_POLICY_MSG.format(botname=_BOTNAME)


# ─────────────── privacy summary content ────────────────────────── #


def test_privacy_msg_no_emoji() -> None:
    assert not _EMOJI_RE.search(_PRIVACY_MSG)


def test_privacy_msg_no_em_dash() -> None:
    assert not _EMDASH_RE.search(_PRIVACY_MSG)


def test_privacy_msg_non_empty() -> None:
    assert _PRIVACY_MSG.strip()


def test_privacy_msg_mentions_user_id() -> None:
    low = _PRIVACY_MSG.lower()
    assert "user id" in low or "user_id" in low or "telegram" in low


def test_privacy_msg_mentions_ban_records() -> None:
    low = _PRIVACY_MSG.lower()
    assert "ban" in low


def test_privacy_msg_third_party_disclaimer() -> None:
    low = _PRIVACY_MSG.lower()
    assert "third" in low or "share" in low


# ─────────────── privacy policy content ─────────────────────────── #


def test_policy_msg_no_emoji() -> None:
    assert not _EMOJI_RE.search(_POLICY_MSG)


def test_policy_msg_no_em_dash() -> None:
    assert not _EMDASH_RE.search(_POLICY_MSG)


def test_policy_msg_has_numbered_sections() -> None:
    """Policy message uses numbered sections (1. 2. 3. ...)."""
    assert "1." in _POLICY_MSG and "2." in _POLICY_MSG


def test_policy_msg_mentions_rights() -> None:
    low = _POLICY_MSG.lower()
    assert "right" in low or "request" in low or "deletion" in low


def test_policy_msg_has_contact_section() -> None:
    low = _POLICY_MSG.lower()
    assert "contact" in low or "reach" in low


# ──────────────── callback handler wiring ──────────────────────── #


async def test_on_privacy_menu_answers_and_edits() -> None:
    q = AsyncMock()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.first_name = _BOTNAME

    await on_privacy_menu(update, ctx)

    q.answer.assert_called_once()
    q.edit_message_text.assert_called_once()
    kwargs = q.edit_message_text.call_args[1]
    assert kwargs.get("parse_mode") == "HTML"


async def test_on_privacy_policy_menu_answers_and_edits() -> None:
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.first_name = _BOTNAME

    await on_privacy_policy_menu(update, ctx)

    q.answer.assert_called_once()
    q.edit_message_text.assert_called_once()
    kwargs = q.edit_message_text.call_args[1]
    assert kwargs.get("parse_mode") == "HTML"


async def test_on_privacy_menu_falls_back_on_missing_botname() -> None:
    """first_name may be None or empty; handler should still work."""
    q = AsyncMock()
    update = MagicMock()
    update.callback_query = q
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.first_name = None  # simulate missing name

    await on_privacy_menu(update, ctx)

    q.edit_message_text.assert_called_once()
    call_text: str = q.edit_message_text.call_args[0][0]
    assert call_text.strip()
