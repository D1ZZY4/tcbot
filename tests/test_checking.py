# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.checking - module metadata and help structure."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.checking as checking

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_checking() -> None:
    assert checking.__module_name__ == "Checking"


def test_help_text_is_non_empty() -> None:
    assert isinstance(checking.__help_text__, str)
    assert checking.__help_text__.strip()


def test_help_text_mentions_checkme() -> None:
    assert "checkme" in checking.__help_text__


def test_help_text_mentions_check() -> None:
    assert "check" in checking.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = checking.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in checking.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_checkme() -> None:
    lookup = dict(checking.__help_sections__)
    assert "checkme" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_check_alias() -> None:
    lookup = dict(checking.__help_sections__)
    assert "/c" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_cme_alias() -> None:
    lookup = dict(checking.__help_sections__)
    assert "cme" in lookup["Commands & Aliases"]


def test_help_sections_no_emdash() -> None:
    for _key, value in checking.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert len(keys) == len(set(keys))


def test_help_sections_has_checkme_section() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "/checkme" in keys


def test_help_sections_has_check_section() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "/check" in keys


def test_help_sections_checkme_mentions_appeal() -> None:
    lookup = dict(checking.__help_sections__)
    assert "appeal" in lookup["/checkme"].lower()


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(checking.__handlers__, list)
    assert len(checking.__handlers__) >= 2


def test_handlers_include_message_and_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler, MessageHandler

    handler_types = {type(h) for h in checking.__handlers__}
    assert MessageHandler in handler_types
    assert CallbackQueryHandler in handler_types


def test_handlers_have_two_message_handlers() -> None:
    from telegram.ext import MessageHandler

    msg_handlers = [h for h in checking.__handlers__ if isinstance(h, MessageHandler)]
    assert len(msg_handlers) == 2


def test_handlers_have_multiple_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler

    cb_handlers = [
        h for h in checking.__handlers__ if isinstance(h, CallbackQueryHandler)
    ]
    assert len(cb_handlers) >= 5


# ───────────────────── Handler behavior: cmd_checkme ────────────── #

_CHECKME_USER_ID = 99
_cmd_checkme = checking.cmd_checkme.__wrapped__.__wrapped__


def _make_checkme_ctx(user_id: int = _CHECKME_USER_ID) -> tuple:
    user = MagicMock()
    user.id = user_id
    user.first_name = "Tester"
    user.username = None
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.username = "mybot"
    return update, ctx


async def test_cmd_checkme_owner_gets_founder_reply(monkeypatch) -> None:
    update, ctx = _make_checkme_ctx(user_id=1)
    monkeypatch.setattr(
        checking.db.users_roles, "get_owner_id", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        checking.db.users_roles, "get_effective_role", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        checking.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    await _cmd_checkme(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "Founder" in reply_text


async def test_cmd_checkme_clean_regular_user(monkeypatch) -> None:
    update, ctx = _make_checkme_ctx()
    monkeypatch.setattr(
        checking.db.users_roles, "get_owner_id", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        checking.db.users_roles, "get_effective_role", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        checking.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    await _cmd_checkme(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "clean" in reply_text.lower() or "no active ban" in reply_text.lower()


async def test_cmd_checkme_banned_user_shows_ban_keyboard(monkeypatch) -> None:
    update, ctx = _make_checkme_ctx()
    ban_doc = {"ban_id": "b1", "reason": "Spam", "date": 1_000_000}
    monkeypatch.setattr(
        checking.db.users_roles, "get_owner_id", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        checking.db.users_roles, "get_effective_role", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        checking.db.bans_db, "get_active_ban", AsyncMock(return_value=ban_doc)
    )
    monkeypatch.setattr(
        checking,
        "_ban_summary",
        AsyncMock(return_value=("You are banned.", None)),
    )
    kb_mock = MagicMock()
    monkeypatch.setattr(
        checking.keyboards, "checkme_ban_kb", MagicMock(return_value=kb_mock)
    )
    await _cmd_checkme(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = update.effective_message.reply_text.call_args[1]
    assert call_kwargs.get("reply_markup") is kb_mock


# ───────────────────── Handler behavior: cmd_check ──────────────── #

_CMD_CHECK_TARGET_ID = 77
_cmd_check = checking.cmd_check.__wrapped__.__wrapped__


def _make_check_ctx(text: str = "/check 77") -> tuple:
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    return update, ctx


async def test_cmd_check_no_target_returns_early(monkeypatch) -> None:
    update, ctx = _make_check_ctx()
    monkeypatch.setattr(
        checking.extraction,
        "extract_target",
        AsyncMock(return_value=(None, None)),
    )
    await _cmd_check(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "Couldn't resolve" in update.effective_message.reply_text.call_args[0][0]


async def test_cmd_check_valid_calls_profile(monkeypatch) -> None:
    update, ctx = _make_check_ctx()
    monkeypatch.setattr(
        checking.extraction,
        "extract_target",
        AsyncMock(return_value=(_CMD_CHECK_TARGET_ID, "Target")),
    )
    monkeypatch.setattr(checking.db.users_cache, "upsert_user", AsyncMock())
    kb_mock = MagicMock()
    monkeypatch.setattr(
        checking.Check, "profile", AsyncMock(return_value=("Profile text.", kb_mock))
    )
    await _cmd_check(update, ctx)
    checking.Check.profile.assert_awaited_once_with(ctx.bot, _CMD_CHECK_TARGET_ID)
    update.effective_message.reply_text.assert_awaited_once()
