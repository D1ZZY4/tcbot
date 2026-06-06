# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.disconnecting - module metadata and help structure."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.disconnecting as disconnecting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_disconnect() -> None:
    assert disconnecting.__module_name__ == "Disconnect"


def test_help_text_is_non_empty() -> None:
    assert isinstance(disconnecting.__help_text__, str)
    assert disconnecting.__help_text__.strip()


def test_help_text_mentions_tcdisconnect() -> None:
    assert "tcdisconnect" in disconnecting.__help_text__


def test_help_text_mentions_rmtc() -> None:
    assert "rmtc" in disconnecting.__help_text__


def test_help_sections_is_list_of_tuples() -> None:
    sections = disconnecting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in disconnecting.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcdisconnect() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "tcdisconnect" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_rmtc() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "rmtc" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_no_emdash() -> None:
    for _key, value in disconnecting.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_has_two_entries() -> None:
    assert isinstance(disconnecting.__handlers__, list)
    assert len(disconnecting.__handlers__) == 2


def test_handlers_are_message_handlers() -> None:
    from telegram.ext import MessageHandler

    for h in disconnecting.__handlers__:
        assert isinstance(h, MessageHandler)


# ─────────────── Handler behavior: cmd_tcdisconnect + cmd_rmtc ──── #

_cmd_tcdisconnect = disconnecting.cmd_tcdisconnect.__wrapped__.__wrapped__
_cmd_rmtc = disconnecting.cmd_rmtc.__wrapped__.__wrapped__.__wrapped__


def _make_disconnect_ctx(chat_type: str = "group") -> tuple:
    user = MagicMock()
    user.id = 7
    user.first_name = "Owner"
    chat = MagicMock()
    chat.type = chat_type
    chat.id = -200
    chat.title = "DiscoGroup"
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
    ctx.bot.send_message = AsyncMock()
    ctx.bot.leave_chat = AsyncMock()
    return update, ctx


async def test_cmd_tcdisconnect_private_chat_returns_early(monkeypatch) -> None:
    update, ctx = _make_disconnect_ctx(chat_type="private")
    await _cmd_tcdisconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "group" in update.effective_message.reply_text.call_args[0][0].lower()


async def test_cmd_tcdisconnect_not_connected_returns_early(monkeypatch) -> None:
    update, ctx = _make_disconnect_ctx()
    monkeypatch.setattr(
        disconnecting.db.groups_db, "is_connected", AsyncMock(return_value=False)
    )
    await _cmd_tcdisconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcdisconnect_member_lookup_fails_returns_role_err(
    monkeypatch,
) -> None:
    update, ctx = _make_disconnect_ctx()
    monkeypatch.setattr(
        disconnecting.db.groups_db, "is_connected", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        disconnecting.db.users_roles, "is_staff", AsyncMock(return_value=False)
    )
    ctx.bot.get_chat_member = AsyncMock(side_effect=Exception("tg_fail"))
    await _cmd_tcdisconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcdisconnect_not_staff_not_owner_returns_early(monkeypatch) -> None:
    update, ctx = _make_disconnect_ctx()
    monkeypatch.setattr(
        disconnecting.db.groups_db, "is_connected", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        disconnecting.db.users_roles, "is_staff", AsyncMock(return_value=False)
    )
    member_mock = MagicMock()
    member_mock.status = "member"
    ctx.bot.get_chat_member = AsyncMock(return_value=member_mock)
    await _cmd_tcdisconnect(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "owner" in update.effective_message.reply_text.call_args[0][0].lower()


def _make_rmtc_ctx(text: str = "/rmtc -200") -> tuple:
    user = MagicMock()
    user.id = 3
    user.first_name = "Staff"
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.leave_chat = AsyncMock()
    return update, ctx


async def test_cmd_rmtc_no_args_returns_usage(monkeypatch) -> None:
    update, ctx = _make_rmtc_ctx(text="/rmtc")
    await _cmd_rmtc(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_rmtc_group_not_found_sends_reply(monkeypatch) -> None:
    update, ctx = _make_rmtc_ctx(text="/rmtc -200")
    monkeypatch.setattr(
        disconnecting.db.groups_db, "deactivate_group", AsyncMock(return_value=0)
    )
    await _cmd_rmtc(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_tcdisconnect_staff_disconnects_group(monkeypatch) -> None:
    """cmd_tcdisconnect for a connected group with a TC staff member disconnects it."""
    update, ctx = _make_disconnect_ctx()
    member_mock = MagicMock()
    member_mock.status = "member"
    ctx.bot.get_chat_member = AsyncMock(return_value=member_mock)
    monkeypatch.setattr(
        disconnecting.db.groups_db, "is_connected", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        disconnecting.db.users_roles, "is_staff", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        disconnecting.db.groups_db, "deactivate_group", AsyncMock(return_value=1)
    )
    mock_cfg = MagicMock()
    mock_cfg.logs = (-300, 0)
    mock_cfg.community_name = "TestCom"
    monkeypatch.setattr(disconnecting, "cfg", mock_cfg)
    await _cmd_tcdisconnect(update, ctx)
    disconnecting.db.groups_db.deactivate_group.assert_awaited_once_with(-200)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_rmtc_success_deactivates_and_replies(monkeypatch) -> None:
    """cmd_rmtc with a valid chat ID and existing group deactivates and replies."""
    update, ctx = _make_rmtc_ctx(text="/rmtc -999")
    monkeypatch.setattr(
        disconnecting.db.groups_db, "deactivate_group", AsyncMock(return_value=1)
    )
    mock_cfg = MagicMock()
    mock_cfg.logs = (-300, 0)
    mock_cfg.community_name = "TestCom"
    monkeypatch.setattr(disconnecting, "cfg", mock_cfg)
    await _cmd_rmtc(update, ctx)
    disconnecting.db.groups_db.deactivate_group.assert_awaited_once_with(-999)
    update.effective_message.reply_text.assert_awaited_once()
