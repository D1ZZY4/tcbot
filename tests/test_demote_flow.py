# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for demote_flow: Demote.remove_role and Demote.execute paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tcbot.modules.helper.workflows import demote_flow
from tcbot.modules.helper.workflows.demote_flow import Demote


def _bot() -> SimpleNamespace:
    return SimpleNamespace(send_message=AsyncMock())


# ─────────────────────── Demote.remove_role ─────────────────────── #


async def test_remove_role_admin_calls_remove_admin(monkeypatch) -> None:
    remove_admin = AsyncMock(return_value=True)
    remove_role = AsyncMock()
    monkeypatch.setattr(demote_flow.db.users_roles, "remove_admin", remove_admin)
    monkeypatch.setattr(demote_flow.db.users_roles, "remove_role", remove_role)

    result = await Demote.remove_role(99, "admin")

    remove_admin.assert_awaited_once_with(99)
    remove_role.assert_not_awaited()
    assert result is True


async def test_remove_role_developer_calls_remove_role(monkeypatch) -> None:
    remove_admin = AsyncMock()
    remove_role = AsyncMock(return_value=True)
    monkeypatch.setattr(demote_flow.db.users_roles, "remove_admin", remove_admin)
    monkeypatch.setattr(demote_flow.db.users_roles, "remove_role", remove_role)

    result = await Demote.remove_role(99, "developer")

    remove_role.assert_awaited_once_with(99)
    remove_admin.assert_not_awaited()
    assert result is True


# ─────────────────────── Demote.execute ─────────────────────────── #


async def test_execute_returns_false_when_role_not_removed(monkeypatch) -> None:
    """If remove_role returns False (user not found), execute returns False immediately."""
    monkeypatch.setattr(Demote, "remove_role", AsyncMock(return_value=False))

    bot = _bot()
    result = await Demote.execute(bot, 99, "Target", "tester", 10, "Admin")

    assert result is False
    bot.send_message.assert_not_awaited()


async def test_execute_manual_demote_logs_and_dms_user(monkeypatch) -> None:
    """Manual demote (no trigger): sends log + DM with 'removed by' wording."""
    monkeypatch.setattr(Demote, "remove_role", AsyncMock(return_value=True))
    monkeypatch.setattr(
        demote_flow.parse_logmsg, "demoted", Mock(return_value="demote log")
    )

    bot = _bot()
    result = await Demote.execute(
        bot, 99, "Target", "tester", 10, "Admin", trigger=None
    )

    assert result is True
    assert bot.send_message.await_count == 2  # log channel + target DM
    # Find the DM (sent to target_id=99)
    calls = [c.args[0] for c in bot.send_message.await_args_list]
    assert 99 in calls
    # DM text should say 'removed by Admin'
    dm_text = [c.args[1] for c in bot.send_message.await_args_list if c.args[0] == 99][
        0
    ]
    assert "removed by" in dm_text.lower()
    assert "Admin" in dm_text


async def test_execute_ban_trigger_mentions_banned_in_dm(monkeypatch) -> None:
    """Auto-demote on ban: DM says the user was 'banned'."""
    monkeypatch.setattr(Demote, "remove_role", AsyncMock(return_value=True))
    monkeypatch.setattr(demote_flow.parse_logmsg, "demoted", Mock(return_value="log"))

    bot = _bot()
    result = await Demote.execute(
        bot, 99, "Target", "developer", 10, "Admin", trigger="ban"
    )

    assert result is True
    dm_text = [c.args[1] for c in bot.send_message.await_args_list if c.args[0] == 99][
        0
    ]
    assert "banned" in dm_text.lower()


async def test_execute_kick_trigger_mentions_kicked_in_dm(monkeypatch) -> None:
    """Auto-demote on kick: DM says the user was 'kicked'."""
    monkeypatch.setattr(Demote, "remove_role", AsyncMock(return_value=True))
    monkeypatch.setattr(demote_flow.parse_logmsg, "demoted", Mock(return_value="log"))

    bot = _bot()
    result = await Demote.execute(
        bot, 99, "Target", "tester", 10, "Admin", trigger="kick"
    )

    assert result is True
    dm_text = [c.args[1] for c in bot.send_message.await_args_list if c.args[0] == 99][
        0
    ]
    assert "kicked" in dm_text.lower()


async def test_execute_log_and_dm_failures_do_not_crash(monkeypatch) -> None:
    """send_message failures are swallowed via return_exceptions; execute still returns True."""
    monkeypatch.setattr(Demote, "remove_role", AsyncMock(return_value=True))
    monkeypatch.setattr(demote_flow.parse_logmsg, "demoted", Mock(return_value="log"))

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("net error")))
    result = await Demote.execute(bot, 99, "Target", "tester", 10, "Admin")

    assert result is True
