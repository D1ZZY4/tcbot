# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.connecting - module metadata and help structure."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.connecting as connecting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_connect() -> None:
    assert connecting.__module_name__ == "Connect"


def test_help_text_is_non_empty() -> None:
    assert isinstance(connecting.__help_text__, str)
    assert connecting.__help_text__.strip()


def test_help_text_mentions_federation() -> None:
    assert "federation" in connecting.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = connecting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in connecting.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in connecting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in connecting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcconnect() -> None:
    lookup = dict(connecting.__help_sections__)
    assert "tcconnect" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tccon_alias() -> None:
    lookup = dict(connecting.__help_sections__)
    assert "tccon" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_admin() -> None:
    lookup = dict(connecting.__help_sections__)
    assert "admin" in lookup["Who can use"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in connecting.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in connecting.__help_sections__]
    assert len(keys) == len(set(keys))


def test_help_sections_contains_required_permissions() -> None:
    keys = [k for k, _ in connecting.__help_sections__]
    assert any("permission" in k.lower() for k in keys)


def test_help_sections_permissions_mentions_ban() -> None:
    lookup = {k.lower(): v for k, v in connecting.__help_sections__}
    perms_text = next(v for k, v in lookup.items() if "permission" in k)
    assert "Ban" in perms_text


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(connecting.__handlers__, list)
    assert len(connecting.__handlers__) >= 2


def test_handlers_include_message_and_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler, ChatMemberHandler, MessageHandler

    handler_types = {type(h) for h in connecting.__handlers__}
    assert MessageHandler in handler_types
    assert ChatMemberHandler in handler_types
    assert CallbackQueryHandler in handler_types


# ────────────────── Handler behavior: cmd_tcconnect ─────────────── #

_cmd_tcconnect = connecting.cmd_tcconnect.__wrapped__.__wrapped__


def _make_connect_ctx(chat_type: str = "group") -> tuple:
    user = MagicMock()
    user.id = 5
    user.first_name = "User"
    chat = MagicMock()
    chat.type = chat_type
    chat.id = -100
    chat.title = "TestGroup"
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.id = 999
    ctx.bot.get_chat_member = AsyncMock()
    return update, ctx


async def test_cmd_tcconnect_private_chat_returns_early(monkeypatch) -> None:
    update, ctx = _make_connect_ctx(chat_type="private")
    await _cmd_tcconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "group" in update.effective_message.reply_text.call_args[0][0].lower()


async def test_cmd_tcconnect_member_lookup_fails_returns_role_err(monkeypatch) -> None:
    update, ctx = _make_connect_ctx()
    ctx.bot.get_chat_member = AsyncMock(side_effect=Exception("tg_timeout"))
    monkeypatch.setattr(
        connecting.db.groups_db, "is_connected", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        connecting.db.groups_db, "get_pending", AsyncMock(return_value=None)
    )
    await _cmd_tcconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcconnect_not_admin_returns_early(monkeypatch) -> None:
    update, ctx = _make_connect_ctx()
    member_mock = MagicMock()
    member_mock.status = "member"
    ctx.bot.get_chat_member = AsyncMock(return_value=member_mock)
    monkeypatch.setattr(
        connecting.db.groups_db, "is_connected", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        connecting.db.groups_db, "get_pending", AsyncMock(return_value=None)
    )
    await _cmd_tcconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcconnect_already_connected_returns_early(monkeypatch) -> None:
    update, ctx = _make_connect_ctx()
    member_mock = MagicMock()
    member_mock.status = "administrator"
    ctx.bot.get_chat_member = AsyncMock(return_value=member_mock)
    monkeypatch.setattr(
        connecting.db.groups_db, "is_connected", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        connecting.db.groups_db, "get_pending", AsyncMock(return_value=None)
    )
    await _cmd_tcconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcconnect_pending_request_returns_early(monkeypatch) -> None:
    update, ctx = _make_connect_ctx()
    member_mock = MagicMock()
    member_mock.status = "administrator"
    ctx.bot.get_chat_member = AsyncMock(return_value=member_mock)
    monkeypatch.setattr(
        connecting.db.groups_db, "is_connected", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        connecting.db.groups_db,
        "get_pending",
        AsyncMock(return_value={"group_id": -100}),
    )
    await _cmd_tcconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
