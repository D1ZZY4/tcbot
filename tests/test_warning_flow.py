# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Regression and executor tests for the warning workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.modules.helper.workflows import warning_flow


def _update(
    reply_text: AsyncMock | None = None,
    chat_id: int = -100,
    chat_title: str = "Test Group",
    admin_id: int = 10,
    admin_fname: str = "Admin",
) -> SimpleNamespace:
    msg = SimpleNamespace(reply_text=reply_text or AsyncMock())
    return SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id, title=chat_title),
        effective_user=SimpleNamespace(id=admin_id, first_name=admin_fname),
    )


def _ctx(send_message: AsyncMock | None = None, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(
            send_message=send_message or AsyncMock(),
            ban_chat_member=AsyncMock(),
            **extra,
        )
    )


# ───────────────────── execute_warn: limit path ─────────────────────── #


async def test_warn_limit_keeps_warns_when_auto_ban_fails(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(side_effect=RuntimeError("no rights")),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    # * Target holds no federation role; auto_demote should be skipped.
    monkeypatch.setattr(
        warning_flow.db.users_roles, "get_effective_role", AsyncMock(return_value=None)
    )

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    clear_warns.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert "auto-ban failed" in msg.reply_text.await_args.args[0]


async def test_warn_limit_clears_warns_after_successful_auto_ban(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    monkeypatch.setattr(
        warning_flow.db.users_roles, "get_effective_role", AsyncMock(return_value=None)
    )

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    clear_warns.assert_awaited_once_with(20, -100)
    msg.reply_text.assert_awaited_once()
    assert "has been banned" in msg.reply_text.await_args.args[0]


async def test_warn_limit_auto_demotes_role_holder_before_ban(monkeypatch) -> None:
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, title="Test Group"),
        effective_user=SimpleNamespace(id=10, first_name="Admin"),
    )
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        )
    )

    add_warn = AsyncMock(return_value=warning_flow.WARN_LIMIT)
    clear_warns = AsyncMock()
    demote_execute_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(warning_flow.db.warns_db, "add_warn", add_warn)
    monkeypatch.setattr(warning_flow.db.warns_db, "clear_warns", clear_warns)
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))
    monkeypatch.setattr(
        warning_flow.db.users_roles,
        "get_effective_role",
        AsyncMock(return_value="tester"),
    )
    monkeypatch.setattr(warning_flow.Demote, "execute", demote_execute_mock)

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    demote_execute_mock.assert_awaited_once()
    # * Demote.execute(bot, target_id, target_name, target_role, admin_id, admin_fname, trigger="ban")
    call_args = demote_execute_mock.await_args
    assert call_args.args[1] == 20
    assert call_args.args[3] == "tester"
    assert call_args.kwargs.get("trigger") == "ban"


# ─────────────────── execute_warn: below-limit path ─────────────────── #


async def test_warn_below_limit_sends_reply_and_log(monkeypatch) -> None:
    """Count below WARN_LIMIT: reply with count/limit and log sent; no ban."""
    update = _update()
    send_message = AsyncMock()
    ctx = _ctx(send_message=send_message)
    count = warning_flow.WARN_LIMIT - 1

    monkeypatch.setattr(
        warning_flow.db.warns_db, "add_warn", AsyncMock(return_value=count)
    )
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="flood",
    )

    ctx.bot.ban_chat_member.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()
    reply = update.effective_message.reply_text.await_args.args[0]
    assert f"({count}/{warning_flow.WARN_LIMIT})" in reply
    assert "flood" in reply
    # Log was sent to the federation log channel
    send_message.assert_awaited_once()


async def test_warn_below_limit_log_failure_still_sends_reply(monkeypatch) -> None:
    """Log send failure is swallowed; the user-facing reply is still sent."""
    update = _update()
    send_message = AsyncMock(side_effect=RuntimeError("net error"))
    ctx = _ctx(send_message=send_message)
    count = 1

    monkeypatch.setattr(
        warning_flow.db.warns_db, "add_warn", AsyncMock(return_value=count)
    )
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
    )

    update.effective_message.reply_text.assert_awaited_once()


async def test_warn_proof_desc_appended_to_reply(monkeypatch) -> None:
    """proof_desc is appended to the reply when supplied."""
    update = _update()
    ctx = _ctx()
    count = 1

    monkeypatch.setattr(
        warning_flow.db.warns_db, "add_warn", AsyncMock(return_value=count)
    )
    monkeypatch.setattr(warning_flow.parse_logmsg, "warn_log", Mock(return_value="log"))

    await warning_flow.execute_warn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
        reason_text="spam",
        proof_desc="https://t.me/proof/42",
    )

    reply = update.effective_message.reply_text.await_args.args[0]
    assert "https://t.me/proof/42" in reply


# ───────────────────────── execute_unwarn ───────────────────────────── #


async def test_execute_unwarn_no_warns_sends_notice(monkeypatch) -> None:
    """Target with zero warns receives a 'no warnings' notice; no DB write."""
    update = _update()
    ctx = _ctx()
    remove_last_warn = AsyncMock()

    monkeypatch.setattr(
        warning_flow.db.warns_db, "warn_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(warning_flow.db.warns_db, "remove_last_warn", remove_last_warn)

    await warning_flow.execute_unwarn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    remove_last_warn.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()
    assert "no warnings" in update.effective_message.reply_text.await_args.args[0]


async def test_execute_unwarn_removes_last_warn_and_notifies(monkeypatch) -> None:
    """One warn removed from a user who has two; reply shows new count."""
    update = _update()
    ctx = _ctx()
    remove_last_warn = AsyncMock()

    monkeypatch.setattr(
        warning_flow.db.warns_db, "warn_count", AsyncMock(return_value=2)
    )
    monkeypatch.setattr(warning_flow.db.warns_db, "remove_last_warn", remove_last_warn)
    monkeypatch.setattr(
        warning_flow.parse_logmsg, "unwarn_log", Mock(return_value="log")
    )

    await warning_flow.execute_unwarn(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    remove_last_warn.assert_awaited_once_with(20, -100)
    update.effective_message.reply_text.assert_awaited_once()
    reply = update.effective_message.reply_text.await_args.args[0]
    # New count is max(2-1, 0) = 1; WARN_LIMIT = 3
    assert "1/3" in reply


# ───────────────────────── execute_warnlist ─────────────────────────── #


async def test_execute_warnlist_no_warns_sends_notice(monkeypatch) -> None:
    update = _update()
    ctx = _ctx()

    monkeypatch.setattr(
        warning_flow.db.warns_db, "get_warns", AsyncMock(return_value=[])
    )

    await warning_flow.execute_warnlist(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    update.effective_message.reply_text.assert_awaited_once()
    assert "no warnings" in update.effective_message.reply_text.await_args.args[0]


async def test_execute_warnlist_with_warns_shows_all_reasons(monkeypatch) -> None:
    update = _update()
    ctx = _ctx()
    warns = [{"reason": "spam"}, {"reason": "flood"}]

    monkeypatch.setattr(
        warning_flow.db.warns_db, "get_warns", AsyncMock(return_value=warns)
    )

    await warning_flow.execute_warnlist(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    reply = update.effective_message.reply_text.await_args.args[0]
    assert "2/3" in reply
    assert "spam" in reply
    assert "flood" in reply


# ─────────────────────── execute_resetwarns ─────────────────────────── #


async def test_execute_resetwarns_no_warns_sends_notice(monkeypatch) -> None:
    update = _update()
    ctx = _ctx()

    monkeypatch.setattr(
        warning_flow.db.warns_db, "clear_warns", AsyncMock(return_value=0)
    )

    await warning_flow.execute_resetwarns(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    update.effective_message.reply_text.assert_awaited_once()
    assert "no warnings" in update.effective_message.reply_text.await_args.args[0]


async def test_execute_resetwarns_clears_all_and_notifies(monkeypatch) -> None:
    update = _update()
    ctx = _ctx()

    monkeypatch.setattr(
        warning_flow.db.warns_db, "clear_warns", AsyncMock(return_value=2)
    )

    await warning_flow.execute_resetwarns(
        cast(Update, update),
        cast(ContextTypes.DEFAULT_TYPE, ctx),
        target_id=20,
        target_name="Target",
    )

    reply = update.effective_message.reply_text.await_args.args[0]
    assert "2" in reply
    assert "Clean slate" in reply


# ─────────────────────── _exec_warn adapter ─────────────────────── #


async def test_exec_warn_pops_user_data_and_calls_execute_warn(monkeypatch) -> None:
    """_exec_warn reads warn_ keys from user_data, clears them, calls execute_warn."""
    execute_warn = AsyncMock()
    monkeypatch.setattr(warning_flow, "execute_warn", execute_warn)

    update = _update()
    ctx = SimpleNamespace(
        bot=SimpleNamespace(
            ban_chat_member=AsyncMock(),
            send_message=AsyncMock(),
        ),
        user_data={
            "warn_target_id": 33,
            "warn_target_name": "Carol",
            "warn_reason": "off-topic",
            "warn_proof_desc": "https://t.me/proof/7",
            "warn_extra_info": "extra",
        },
    )

    await warning_flow._exec_warn(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    execute_warn.assert_awaited_once()
    # * All warn_ keys must be removed from user_data
    for key in (
        "warn_target_id",
        "warn_target_name",
        "warn_reason",
        "warn_proof_desc",
        "warn_extra_info",
    ):
        assert key not in ctx.user_data


async def test_exec_warn_empty_user_data_uses_defaults(monkeypatch) -> None:
    """When warn_ keys are missing, _exec_warn calls execute_warn with zero-value defaults."""
    execute_warn = AsyncMock()
    monkeypatch.setattr(warning_flow, "execute_warn", execute_warn)

    update = _update()
    ctx = SimpleNamespace(
        bot=SimpleNamespace(ban_chat_member=AsyncMock()),
        user_data={},
    )

    await warning_flow._exec_warn(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    execute_warn.assert_awaited_once()
    args = execute_warn.await_args
    # * target_id defaults to 0, proof_desc defaults to None
    target_id_passed = args.kwargs.get("target_id") or args.args[2]
    assert target_id_passed == 0
    proof_desc_passed = args.kwargs.get("proof_desc")
    assert proof_desc_passed is None


# ──────────────── warn_conversation factory ──────────────────────── #


def test_warn_conversation_returns_conversation_handler() -> None:
    """warn_conversation must return a ConversationHandler instance."""
    from telegram.ext import ConversationHandler, filters

    async def _entry(update, context): ...

    handler = warning_flow.warn_conversation(_entry, filters.TEXT)
    assert isinstance(handler, ConversationHandler)


def test_warn_conversation_has_entry_point() -> None:
    """The returned ConversationHandler must have exactly one entry point."""
    from telegram.ext import filters

    async def _entry(update, context): ...

    handler = warning_flow.warn_conversation(_entry, filters.TEXT)
    assert len(handler.entry_points) == 1


def test_warn_conversation_with_escape_filter() -> None:
    """warn_conversation with escape_filter must still return a ConversationHandler."""
    from telegram.ext import ConversationHandler, filters

    async def _entry(update, context): ...

    handler = warning_flow.warn_conversation(
        _entry, filters.TEXT, escape_filter=filters.COMMAND
    )
    assert isinstance(handler, ConversationHandler)
