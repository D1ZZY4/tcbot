# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.maintenance - module metadata and pure helpers."""

from __future__ import annotations

from types import SimpleNamespace

import tcbot.modules.maintenance as maintenance
from tcbot.modules.maintenance import _should_remove

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_cleanup() -> None:
    assert maintenance.__module_name__ == "Cleanup"


def test_help_text_is_non_empty() -> None:
    assert isinstance(maintenance.__help_text__, str)
    assert maintenance.__help_text__.strip()


def test_help_sections_is_list_of_tuples() -> None:
    sections = maintenance.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in maintenance.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_leaveall() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "leaveall" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_cleanup() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "cleanup" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_founder() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "Founder" in lookup["Who can use"]


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_no_emdash() -> None:
    for _key, value in maintenance.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert len(keys) == len(set(keys))


# ────────────────────── _should_remove pure logic ───────────────── #


async def test_should_remove_returns_false_for_admin_member(monkeypatch) -> None:
    """Bot is still an active admin: should_remove must return False."""
    member = SimpleNamespace(status="administrator")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is False


async def test_should_remove_returns_true_for_kicked_status(monkeypatch) -> None:
    """Bot was kicked: should_remove must return True."""
    member = SimpleNamespace(status="kicked")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_for_left_status(monkeypatch) -> None:
    """Bot shows 'left' status: should_remove must return True."""
    member = SimpleNamespace(status="left")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_on_exception(monkeypatch) -> None:
    """Network error during membership check: should_remove must return True."""

    async def raise_exc(chat_id, uid):
        raise Exception("timeout")

    bot = SimpleNamespace(id=1, get_chat_member=raise_exc)
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_for_member_status(monkeypatch) -> None:
    """Bot degraded to plain 'member': should_remove must return False (still present)."""
    member = SimpleNamespace(status="member")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is False


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(maintenance.__handlers__, list)
    assert len(maintenance.__handlers__) >= 2


def test_handlers_are_message_handlers() -> None:
    from telegram.ext import MessageHandler

    for h in maintenance.__handlers__:
        assert isinstance(h, MessageHandler)


# ──────────────────────────── Helpers ───────────────────────────── #


async def _coro(value):
    return value


# ──────────────── cmd_leaveall / cmd_cleanup behaviour ───────────── #

_cmd_leaveall = maintenance.cmd_leaveall.__wrapped__.__wrapped__.__wrapped__
_cmd_cleanup = maintenance.cmd_cleanup.__wrapped__.__wrapped__.__wrapped__


def _make_env(*, user_id: int = 1, name: str = "Admin") -> object:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    status = AsyncMock()
    status.edit_text = AsyncMock()

    msg = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    user = MagicMock()
    user.id = user_id
    user.first_name = name

    update = MagicMock()
    update.effective_message = msg
    update.effective_user = user

    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.leave_chat = AsyncMock()

    return SimpleNamespace(update=update, ctx=ctx, msg=msg, status=status)


async def test_cmd_leaveall_no_groups_replies_error() -> None:
    """No active groups must produce the no-connected-groups error reply."""
    from unittest.mock import AsyncMock, patch

    env = _make_env()
    with patch("tcbot.modules.maintenance.db") as mock_db:
        mock_db.groups_db.active_groups = AsyncMock(return_value=[])
        await _cmd_leaveall(env.update, env.ctx)

    from tcbot.modules.helper.replies import ERR_NO_CONNECTED_GROUPS

    env.msg.reply_text.assert_called_once_with(ERR_NO_CONNECTED_GROUPS)


async def test_cmd_leaveall_sends_status_before_leaving() -> None:
    """cmd_leaveall must send a status reply before processing any groups."""
    from unittest.mock import AsyncMock, patch

    grps = [{"chat_id": -100, "title": "Test Group"}]
    env = _make_env()
    with (
        patch("tcbot.modules.maintenance.db") as mock_db,
        patch("tcbot.modules.maintenance.cfg") as mock_cfg,
        patch(
            "tcbot.modules.maintenance._leave_one",
            new=AsyncMock(return_value=[None, None, None]),
        ),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        mock_cfg.logs = (-10001, None)
        await _cmd_leaveall(env.update, env.ctx)

    first_reply: str = env.msg.reply_text.call_args_list[0][0][0]
    assert "1" in first_reply or "group" in first_reply.lower()


async def test_cmd_leaveall_edits_status_with_final_count() -> None:
    """cmd_leaveall must edit the status message once with success/fail counts."""
    from unittest.mock import AsyncMock, patch

    grps = [{"chat_id": -100, "title": "Group"}]
    env = _make_env()
    with (
        patch("tcbot.modules.maintenance.db") as mock_db,
        patch("tcbot.modules.maintenance.cfg") as mock_cfg,
        patch(
            "tcbot.modules.maintenance._leave_one",
            new=AsyncMock(return_value=[None, None, None]),
        ),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        mock_cfg.logs = (-10001, None)
        await _cmd_leaveall(env.update, env.ctx)

    env.status.edit_text.assert_called_once()
    edit_text: str = env.status.edit_text.call_args[0][0]
    assert "1" in edit_text


async def test_cmd_cleanup_no_stale_replies_zero() -> None:
    """If no stale groups are found, cleanup must reply with 0 removed."""
    from unittest.mock import AsyncMock, patch

    grps = [{"chat_id": -100}]
    env = _make_env()
    with (
        patch("tcbot.modules.maintenance.db") as mock_db,
        patch(
            "tcbot.modules.maintenance._should_remove",
            new=AsyncMock(return_value=False),
        ),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        await _cmd_cleanup(env.update, env.ctx)

    reply: str = env.msg.reply_text.call_args[0][0]
    assert "0" in reply


async def test_cmd_cleanup_stale_group_deactivates_and_replies() -> None:
    """Stale groups must be deactivated and the removed count reported."""
    from unittest.mock import AsyncMock, patch

    grps = [{"chat_id": -100}, {"chat_id": -200}]
    env = _make_env()
    with (
        patch("tcbot.modules.maintenance.db") as mock_db,
        patch(
            "tcbot.modules.maintenance._should_remove",
            new=AsyncMock(side_effect=[True, False]),
        ),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        mock_db.groups_db.deactivate_group = AsyncMock()
        await _cmd_cleanup(env.update, env.ctx)

    mock_db.groups_db.deactivate_group.assert_called_once_with(-100)
    reply: str = env.msg.reply_text.call_args[0][0]
    assert "1" in reply
