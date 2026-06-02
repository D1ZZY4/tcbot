# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for connected_flow: BuildConnection pure helpers and event handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from telegram.constants import ChatMemberStatus

from tcbot.modules.helper.workflows import connected_flow
from tcbot.modules.helper.workflows.connected_flow import BuildConnection


def _build() -> BuildConnection:
    return BuildConnection("Test Federation")


def _bot(**kw) -> SimpleNamespace:
    defaults = dict(
        id=1,
        get_chat=AsyncMock(return_value=SimpleNamespace(username="testgroup")),
        get_chat_member=AsyncMock(),
        send_message=AsyncMock(),
        ban_chat_member=AsyncMock(),
        edit_message_text=AsyncMock(),
        leave_chat=AsyncMock(),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ─────────────────── Pure text helpers ──────────────────────────── #


def test_join_prompt_contains_community_name() -> None:
    bc = _build()
    assert "Test Federation" in bc.join_prompt()


def test_connected_message_is_nonempty() -> None:
    bc = _build()
    assert bc.connected_message()
    assert "Test Federation" in bc.connected_message()


def test_declined_message_is_nonempty() -> None:
    bc = _build()
    assert bc.declined_message()


def test_already_connected_message_contains_community_name() -> None:
    bc = _build()
    assert "Test Federation" in bc.already_connected_message()


def test_perms_required_message_is_nonempty() -> None:
    bc = _build()
    assert bc.perms_required_message()


# ────────────────────── join_keyboard ───────────────────────────── #


def test_join_keyboard_has_connect_and_cancel() -> None:
    bc = _build()
    kb = bc.join_keyboard()
    buttons = kb.inline_keyboard[0]
    cb_datas = {b.callback_data for b in buttons}
    assert bc.join_callback in cb_datas
    assert bc.cancel_callback in cb_datas


# ───────────────────── check_perms ──────────────────────────────── #


def test_check_perms_all_present_returns_true() -> None:
    bc = _build()
    member = SimpleNamespace(
        can_delete_messages=True,
        can_restrict_members=True,
        can_invite_users=True,
    )
    assert bc.check_perms(member) is True


def test_check_perms_missing_one_returns_false() -> None:
    bc = _build()
    member = SimpleNamespace(
        can_delete_messages=True,
        can_restrict_members=False,
        can_invite_users=True,
    )
    assert bc.check_perms(member) is False


def test_check_perms_all_missing_returns_false() -> None:
    bc = _build()
    member = SimpleNamespace()
    assert bc.check_perms(member) is False


# ─────────────────── complete_join ──────────────────────────────── #


async def test_complete_join_applies_bans_and_sends_log(monkeypatch) -> None:
    monkeypatch.setattr(
        connected_flow.db.bans_db,
        "active_ban_user_ids",
        AsyncMock(return_value=[10, 20]),
    )
    monkeypatch.setattr(connected_flow.db.groups_db, "add_group", AsyncMock())
    monkeypatch.setattr(connected_flow.db.groups_db, "remove_pending", AsyncMock())
    monkeypatch.setattr(
        connected_flow.fan_out,
        "__call__",
        Mock(return_value=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        connected_flow.parse_logmsg,
        "group_connected_log",
        Mock(return_value="connected log"),
    )

    bot = _bot()
    bc = _build()
    await bc.complete_join(-100, "Test Chat", 99, "Owner", bot)

    bot.send_message.assert_awaited_once()


# ─────────────────── on_bot_added ───────────────────────────────── #


async def test_on_bot_added_no_cmc_returns_early(monkeypatch) -> None:
    bc = _build()
    update = SimpleNamespace(my_chat_member=None)
    ctx = SimpleNamespace(bot=_bot())
    # Must not raise
    await bc.on_bot_added(update, ctx)


async def test_on_bot_added_bot_removed_deactivates_group(monkeypatch) -> None:
    monkeypatch.setattr(
        connected_flow.db.groups_db, "is_connected", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(connected_flow.db.groups_db, "deactivate_group", AsyncMock())
    monkeypatch.setattr(connected_flow.db.groups_db, "remove_pending", AsyncMock())

    bc = _build()
    chat = SimpleNamespace(id=-100, type="supergroup", title="Chat")
    new_member = SimpleNamespace(status=ChatMemberStatus.LEFT)
    cmc = SimpleNamespace(
        chat=chat, new_chat_member=new_member, from_user=SimpleNamespace(id=1)
    )
    update = SimpleNamespace(my_chat_member=cmc)
    ctx = SimpleNamespace(bot=_bot())

    await bc.on_bot_added(update, ctx)

    connected_flow.db.groups_db.deactivate_group.assert_awaited_once_with(-100)


async def test_on_bot_added_non_group_chat_skipped(monkeypatch) -> None:
    bc = _build()
    chat = SimpleNamespace(id=-100, type="private", title=None)
    new_member = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    cmc = SimpleNamespace(
        chat=chat, new_chat_member=new_member, from_user=SimpleNamespace(id=1)
    )
    update = SimpleNamespace(my_chat_member=cmc)
    ctx = SimpleNamespace(bot=_bot())
    # Should return early without hitting DB
    await bc.on_bot_added(update, ctx)


# ─────────────────── on_join_decision ───────────────────────────── #


async def test_on_join_decision_rejects_non_owner(monkeypatch) -> None:
    bc = _build()

    non_owner = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    bot = _bot(get_chat_member=AsyncMock(return_value=non_owner))
    q = SimpleNamespace(answer=AsyncMock(), data=bc.join_callback)
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(id=-100, title="Chat"),
        effective_user=SimpleNamespace(id=55, first_name="User"),
    )
    ctx = SimpleNamespace(bot=bot)

    await bc.on_join_decision(update, ctx)

    q.answer.assert_awaited_once()
    call_kwargs = q.answer.await_args.kwargs
    assert call_kwargs.get("show_alert") is True


async def test_on_join_decision_cancel_leaves_group(monkeypatch) -> None:
    monkeypatch.setattr(connected_flow.db.groups_db, "remove_pending", AsyncMock())
    monkeypatch.setattr(
        connected_flow.parse_logmsg,
        "group_connection_rejected_log",
        Mock(return_value="rejected log"),
    )

    bc = _build()
    owner = SimpleNamespace(status=ChatMemberStatus.OWNER)
    bot = _bot(get_chat_member=AsyncMock(return_value=owner))
    q = SimpleNamespace(
        answer=AsyncMock(),
        data=bc.cancel_callback,
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(id=-100, title="Chat"),
        effective_user=SimpleNamespace(id=55, first_name="Owner"),
    )
    ctx = SimpleNamespace(bot=bot)

    await bc.on_join_decision(update, ctx)

    bot.leave_chat.assert_awaited_once_with(-100)
    q.edit_message_text.assert_awaited_once()
