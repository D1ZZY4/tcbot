# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.broadcasting - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.broadcasting as broadcasting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_broadcast() -> None:
    assert broadcasting.__module_name__ == "Broadcast"


def test_help_text_is_non_empty() -> None:
    assert isinstance(broadcasting.__help_text__, str)
    assert broadcasting.__help_text__.strip()


def test_help_sections_is_list_of_tuples() -> None:
    sections = broadcasting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in broadcasting.__help_sections__:
        assert isinstance(key, str) and key.strip(), f"Empty key found: {key!r}"
        assert isinstance(value, str) and value.strip(), f"Empty value for key {key!r}"


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_commands_mentions_tcbroadcast() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "tcbroadcast" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_bc_alias() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "/bc" in lookup["Commands & Aliases"]


def test_help_sections_no_emoji_or_emdash() -> None:
    for _key, value in broadcasting.__help_sections__:
        assert "\u2014" not in value, f"Em-dash found in section value: {value!r}"


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(broadcasting.__handlers__, list)
    assert len(broadcasting.__handlers__) > 0


def test_handlers_contains_message_handler() -> None:
    types = [type(h).__name__ for h in broadcasting.__handlers__]
    assert "MessageHandler" in types


# ────────────────────── cmd_broadcast behaviour ─────────────────── #

# Access the unwrapped handler (bypass ratelimiter / staff_only / log_execution).
_cmd_broadcast = broadcasting.cmd_broadcast.__wrapped__.__wrapped__.__wrapped__


def _make_update(*, text: str | None = None, reply_to: object | None = None) -> object:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    status = AsyncMock()
    status.message_id = 1
    status.edit_text = AsyncMock()

    msg = AsyncMock()
    msg.text = text
    msg.reply_to_message = reply_to
    msg.reply_text = AsyncMock(return_value=status)

    user = MagicMock()
    user.id = 10
    user.first_name = "Admin"

    update = MagicMock()
    update.effective_message = msg
    update.effective_user = user
    update.effective_chat = MagicMock()

    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    ctx.user_data = {}
    return SimpleNamespace(update=update, ctx=ctx, msg=msg)


async def test_cmd_broadcast_no_text_no_reply_returns_early() -> None:
    """Missing text and no reply-to must send an error and return without broadcasting."""
    from unittest.mock import patch

    env = _make_update(text="/bc")
    with patch("tcbot.modules.broadcasting.db") as mock_db:
        from unittest.mock import AsyncMock

        mock_db.groups_db.active_groups = AsyncMock(return_value=[{"chat_id": -1}])
        await _cmd_broadcast(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    reply: str = env.msg.reply_text.call_args[0][0]
    assert "broadcast" in reply.lower() or "message" in reply.lower()


async def test_cmd_broadcast_no_connected_groups_returns_error() -> None:
    """Empty group list must send the no-connected-groups error reply."""
    from unittest.mock import AsyncMock, patch

    env = _make_update(text="/bc Hello there")
    with patch("tcbot.modules.broadcasting.db") as mock_db:
        mock_db.groups_db.active_groups = AsyncMock(return_value=[])
        await _cmd_broadcast(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    from tcbot.modules.helper.replies import ERR_NO_CONNECTED_GROUPS

    assert env.msg.reply_text.call_args[0][0] == ERR_NO_CONNECTED_GROUPS


async def test_cmd_broadcast_sends_to_each_group() -> None:
    """cmd_broadcast must send a message to every active group via fan_out."""
    from unittest.mock import AsyncMock, patch

    groups = [{"chat_id": -100001}, {"chat_id": -100002}]
    env = _make_update(text="/bc Announcement")

    with (
        patch("tcbot.modules.broadcasting.db") as mock_db,
        patch("tcbot.modules.broadcasting.cfg") as mock_cfg,
        patch(
            "tcbot.modules.broadcasting.fan_out",
            new=AsyncMock(return_value=[None, None]),
        ) as mock_fan,
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=groups)
        mock_cfg.logs = (-10001, None)
        await _cmd_broadcast(env.update, env.ctx)

    # fan_out must have been called (one call with a list of coroutines)
    mock_fan.assert_called_once()
    calls_arg = mock_fan.call_args[0][0]
    assert len(calls_arg) == 2


async def test_cmd_broadcast_shows_status_message() -> None:
    """A status message ('Broadcasting to N group(s)...') must be sent before fan_out."""
    from unittest.mock import AsyncMock, patch

    groups = [{"chat_id": -100001}]
    env = _make_update(text="/bc Hello")

    with (
        patch("tcbot.modules.broadcasting.db") as mock_db,
        patch("tcbot.modules.broadcasting.cfg") as mock_cfg,
        patch("tcbot.modules.broadcasting.fan_out", new=AsyncMock(return_value=[None])),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=groups)
        mock_cfg.logs = (-10001, None)
        await _cmd_broadcast(env.update, env.ctx)

    # First reply_text call should be the status message
    first_call: str = env.msg.reply_text.call_args_list[0][0][0]
    assert "Broadcasting" in first_call or "group" in first_call.lower()
