# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.admins - module metadata and help structure."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.admins as admins
from tcbot.modules.helper.identity import Identity

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_admins() -> None:
    assert admins.__module_name__ == "Admins"


def test_help_text_is_non_empty() -> None:
    assert isinstance(admins.__help_text__, str)
    assert admins.__help_text__.strip()


def test_help_text_mentions_promote() -> None:
    assert "romot" in admins.__help_text__


def test_help_text_mentions_demote() -> None:
    assert "emot" in admins.__help_text__


def test_help_sections_is_list_of_tuples() -> None:
    sections = admins.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in admins.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_contains_role_hierarchy() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Role Hierarchy" in keys


def test_help_sections_commands_mentions_tcpromote() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcpromote" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcdemote() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcdemote" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_transferowner() -> None:
    lookup = dict(admins.__help_sections__)
    assert "transferowner" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcpromoterequests() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcpromoterequests" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_founder() -> None:
    lookup = dict(admins.__help_sections__)
    assert "Founder" in lookup["Who can use"]


def test_help_sections_who_can_use_references_admin() -> None:
    lookup = dict(admins.__help_sections__)
    assert "Admin" in lookup["Who can use"]


def test_help_sections_role_hierarchy_lists_four_ranks() -> None:
    lookup = dict(admins.__help_sections__)
    hierarchy = lookup["Role Hierarchy"]
    for role in ("Founder", "Admin", "Developer", "Tester"):
        assert role in hierarchy, f"Role hierarchy missing: {role}"


def test_help_sections_no_emdash() -> None:
    for _key, value in admins.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(admins.__handlers__, list)
    assert len(admins.__handlers__) >= 5


def test_handlers_include_message_and_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler, MessageHandler

    handler_types = {type(h) for h in admins.__handlers__}
    assert MessageHandler in handler_types
    assert CallbackQueryHandler in handler_types


def test_handlers_have_five_message_handlers() -> None:
    from telegram.ext import MessageHandler

    msg_handlers = [h for h in admins.__handlers__ if isinstance(h, MessageHandler)]
    assert len(msg_handlers) == 5


def test_handlers_have_callback_handlers_for_promo_and_demote() -> None:
    from telegram.ext import CallbackQueryHandler

    cb_handlers = [
        h for h in admins.__handlers__ if isinstance(h, CallbackQueryHandler)
    ]
    assert len(cb_handlers) >= 3


# ──────────────────── Handler behavior: cmd_promote ─────────────── #

_PROMOTE_ADMIN_ID = 10
_PROMOTE_TARGET_ID = 42
_cmd_promote = admins.cmd_promote.__wrapped__.__wrapped__.__wrapped__


def _make_promote_ctx(text: str = "/tcpromote 42") -> tuple:
    user = MagicMock()
    user.id = _PROMOTE_ADMIN_ID
    user.first_name = "Admin"
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.id = 999
    return update, ctx


async def test_cmd_promote_no_target_returns_early(monkeypatch) -> None:
    update, ctx = _make_promote_ctx()
    monkeypatch.setattr(
        admins.db.users_roles,
        "get_effective_role",
        AsyncMock(return_value="admin"),
    )
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(None, None)),
    )
    await _cmd_promote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "Specify" in update.effective_message.reply_text.call_args[0][0]


async def test_cmd_promote_refused_identity_returns_early(monkeypatch) -> None:
    update, ctx = _make_promote_ctx()

    async def _mock_role(uid: int) -> str:
        return "admin"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_PROMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_PROMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(
        admins.identity, "refuse_message", MagicMock(return_value="Refused.")
    )
    await _cmd_promote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_promote_with_role_arg_calls_execute(monkeypatch) -> None:
    update, ctx = _make_promote_ctx("/tcpromote 42 admin")

    async def _mock_role(uid: int) -> str:
        return "admin"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_PROMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_PROMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(admins.identity, "refuse_message", MagicMock(return_value=None))
    monkeypatch.setattr(admins, "ROLE_ALIASES", {"admin": "admin"})
    execute_mock = AsyncMock(return_value=(True, "Promoted."))
    monkeypatch.setattr(admins.Promote, "execute", execute_mock)
    await _cmd_promote(update, ctx)
    execute_mock.assert_awaited_once()
    update.effective_message.reply_text.assert_awaited()


async def test_cmd_promote_no_role_arg_shows_keyboard(monkeypatch) -> None:
    update, ctx = _make_promote_ctx("/tcpromote 42")

    async def _mock_role(uid: int) -> str:
        return "admin"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_PROMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_PROMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(admins.identity, "refuse_message", MagicMock(return_value=None))
    monkeypatch.setattr(
        admins.Promote, "available_roles_for", MagicMock(return_value=["tester"])
    )
    kb_mock = MagicMock()
    monkeypatch.setattr(
        admins.keyboards, "promote_role_kb", MagicMock(return_value=kb_mock)
    )
    await _cmd_promote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = update.effective_message.reply_text.call_args[1]
    assert call_kwargs.get("reply_markup") is kb_mock


# ──────────────────── Handler behavior: cmd_demote ──────────────── #

_DEMOTE_ADMIN_ID = 11
_DEMOTE_TARGET_ID = 55
_cmd_demote = admins.cmd_demote.__wrapped__.__wrapped__.__wrapped__


def _make_demote_ctx(text: str = "/tcdemote 55") -> tuple:
    user = MagicMock()
    user.id = _DEMOTE_ADMIN_ID
    user.first_name = "Admin"
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.id = 999
    return update, ctx


async def test_cmd_demote_no_target_returns_early(monkeypatch) -> None:
    update, ctx = _make_demote_ctx()
    monkeypatch.setattr(
        admins.db.users_roles,
        "get_effective_role",
        AsyncMock(return_value="admin"),
    )
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(None, None)),
    )
    await _cmd_demote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    assert "Specify" in update.effective_message.reply_text.call_args[0][0]


async def test_cmd_demote_refused_identity_returns_early(monkeypatch) -> None:
    update, ctx = _make_demote_ctx()

    async def _mock_role(uid: int) -> str:
        return "admin"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_DEMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_DEMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(
        admins.identity, "refuse_message", MagicMock(return_value="Cannot demote.")
    )
    await _cmd_demote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_demote_no_target_role_returns_early(monkeypatch) -> None:
    update, ctx = _make_demote_ctx()

    async def _mock_role(uid: int) -> str | None:
        return "admin" if uid == _DEMOTE_ADMIN_ID else None

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_DEMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_DEMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(admins.identity, "refuse_message", MagicMock(return_value=None))
    await _cmd_demote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_demote_admin_target_non_founder_returns_early(monkeypatch) -> None:
    update, ctx = _make_demote_ctx()

    async def _mock_role(uid: int) -> str:
        return "admin"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_DEMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_DEMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(admins.identity, "refuse_message", MagicMock(return_value=None))
    await _cmd_demote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_cmd_demote_valid_shows_confirmation_keyboard(monkeypatch) -> None:
    update, ctx = _make_demote_ctx()

    async def _mock_role(uid: int) -> str:
        return "admin" if uid == _DEMOTE_ADMIN_ID else "tester"

    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _mock_role)
    monkeypatch.setattr(
        admins.extraction,
        "extract_target",
        AsyncMock(return_value=(_DEMOTE_TARGET_ID, "Target")),
    )
    ident = Identity(kind="user", target_id=_DEMOTE_TARGET_ID, fname="Target")
    monkeypatch.setattr(admins.identity, "classify", AsyncMock(return_value=ident))
    monkeypatch.setattr(admins.identity, "refuse_message", MagicMock(return_value=None))
    kb_mock = MagicMock()
    monkeypatch.setattr(
        admins.keyboards, "demote_confirm_kb", MagicMock(return_value=kb_mock)
    )
    await _cmd_demote(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = update.effective_message.reply_text.call_args[1]
    assert call_kwargs.get("reply_markup") is kb_mock
