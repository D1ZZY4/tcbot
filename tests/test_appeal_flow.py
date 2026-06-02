# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""State-machine tests for BuildAppeal: entry, validation, submission, and decisions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper.workflows import appeal_flow
from tcbot.modules.helper.workflows.appeal_flow import WAITING_APPEAL, BuildAppeal

# ─────────────────────────── Fixtures / helpers ──────────────────────── #


def _ba() -> BuildAppeal:
    return BuildAppeal("Test Federation", "@TestLogs")


def _private_update(
    text: str = "",
    uid: int = 99,
    fname: str = "User",
    username: str | None = "tuser",
    last_name: str | None = None,
    reply_text: AsyncMock | None = None,
) -> SimpleNamespace:
    msg = SimpleNamespace(
        text=text,
        reply_text=reply_text or AsyncMock(),
        forward=AsyncMock(return_value=SimpleNamespace(message_id=500)),
    )
    return SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=uid, type="private"),
        effective_user=SimpleNamespace(
            id=uid,
            first_name=fname,
            username=username,
            last_name=last_name,
        ),
    )


def _ctx(user_data: dict | None = None, bot=None) -> SimpleNamespace:
    return SimpleNamespace(
        user_data=user_data if user_data is not None else {},
        bot=bot
        or SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=888)),
            edit_message_text=AsyncMock(),
        ),
    )


# ──────────────────────────── _on_entry ─────────────────────────────── #


async def test_on_entry_bad_pattern_returns_end() -> None:
    """A /start payload that does not match appeal_<10 alnum> ends immediately."""
    ba = _ba()
    update = _private_update(text="/start notanappeal")
    ctx = _ctx()

    result = await ba._on_entry(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_not_awaited()


async def test_on_entry_valid_pattern_invokes_start(monkeypatch) -> None:
    """A well-formed /start appeal_<10chars> deep link reaches _start."""
    ba = _ba()
    ban_id = "abcd123456"  # 10 alnum chars

    # Mock what _start needs so it runs without real DB
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(return_value=None),  # triggers "invalid or expired" path
    )
    update = _private_update(text=f"/start appeal_{ban_id}")
    ctx = _ctx()

    result = await ba._on_entry(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    # _start was reached; it rejected because ban is None (returns END)
    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_awaited_once()
    assert "invalid" in update.effective_message.reply_text.await_args.args[0].lower()


# ───────────────────────────── _start ───────────────────────────────── #


async def test_start_rejects_non_private_chat(monkeypatch) -> None:
    ba = _ba()
    update = _private_update()
    update.effective_chat.type = "group"

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()), "ban1234567x"
    )

    assert result == ConversationHandler.END
    update.effective_message.reply_text.assert_awaited_once()
    assert "private" in update.effective_message.reply_text.await_args.args[0].lower()


async def test_start_rejects_missing_ban(monkeypatch) -> None:
    ba = _ba()
    monkeypatch.setattr(appeal_flow.db.bans_db, "get_ban", AsyncMock(return_value=None))
    update = _private_update()
    ctx = _ctx()

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx), "ban1234567x"
    )

    assert result == ConversationHandler.END
    assert "invalid" in update.effective_message.reply_text.await_args.args[0].lower()


async def test_start_rejects_inactive_ban(monkeypatch) -> None:
    ba = _ba()
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(return_value={"banned_user_id": 99, "is_active": False}),
    )
    update = _private_update()

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()), "ban1234567x"
    )

    assert result == ConversationHandler.END
    assert "invalid" in update.effective_message.reply_text.await_args.args[0].lower()


async def test_start_rejects_wrong_user(monkeypatch) -> None:
    ba = _ba()
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(
            return_value={"banned_user_id": 1000, "is_active": True}
        ),  # different uid
    )
    update = _private_update(uid=99)

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()), "ban1234567x"
    )

    assert result == ConversationHandler.END
    reply = update.effective_message.reply_text.await_args.args[0]
    assert "belong" in reply.lower()


async def test_start_rejects_pending_review(monkeypatch) -> None:
    ba = _ba()
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(
            return_value={
                "banned_user_id": 99,
                "is_active": True,
                "review_message_id": 42,
            }
        ),
    )
    update = _private_update(uid=99)

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()), "ban1234567x"
    )

    assert result == ConversationHandler.END
    assert "pending" in update.effective_message.reply_text.await_args.args[0].lower()


async def test_start_happy_path_enters_waiting_state(monkeypatch) -> None:
    """Valid link for the correct user with an active ban enters WAITING_APPEAL."""
    ba = _ba()
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(
            return_value={
                "banned_user_id": 99,
                "is_active": True,
                "log_message_id": 77,
            }
        ),
    )

    instr_msg = SimpleNamespace(message_id=200)
    reply_mock = AsyncMock(return_value=instr_msg)
    update = _private_update(uid=99, reply_text=reply_mock)
    user_data: dict = {}
    ctx = _ctx(user_data=user_data)

    result = await ba._start(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx), "ban1234567x"
    )

    assert result == WAITING_APPEAL
    assert user_data["appeal_ban_id"] == "ban1234567x"
    assert user_data["appeal_log_msg_id"] == 77
    assert user_data["appeal_instruction_msg_id"] == 200


# ──────────────────────────── _on_cancel ────────────────────────────── #


async def test_on_cancel_clears_state_and_ends() -> None:
    ba = _ba()
    q = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=q)
    user_data = {
        "appeal_ban_id": "ban1234567x",
        "appeal_log_msg_id": 77,
        "appeal_instruction_msg_id": 200,
    }
    ctx = _ctx(user_data=user_data)

    result = await ba._on_cancel(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    q.answer.assert_awaited_once()
    q.edit_message_text.assert_awaited_once()
    assert "cancelled" in q.edit_message_text.await_args.args[0].lower()
    # State keys must be cleared
    assert "appeal_ban_id" not in user_data
    assert "appeal_log_msg_id" not in user_data
    assert "appeal_instruction_msg_id" not in user_data


# ──────────────────────────── _on_message ───────────────────────────── #


async def test_on_message_non_appeal_text_stays_waiting() -> None:
    """Text that does not start with #appeal keeps the session open."""
    ba = _ba()
    update = _private_update(text="Hello, can I appeal?")
    ctx = _ctx(user_data={"appeal_ban_id": "ban1234567x"})

    result = await ba._on_message(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == WAITING_APPEAL
    update.effective_message.reply_text.assert_not_awaited()


async def test_on_message_missing_log_ref_stays_waiting(monkeypatch) -> None:
    """#appeal text that omits the required log message ID stays in state."""
    ba = _ba()
    monkeypatch.setattr(
        appeal_flow.parse_logmsg,
        "appeal_received_log",
        Mock(return_value="review"),
    )
    update = _private_update(text="#appeal\nClarification: I was innocent.")
    ctx = _ctx(
        user_data={
            "appeal_ban_id": "ban1234567x",
            "appeal_log_msg_id": 999,  # user must reference this
        }
    )

    result = await ba._on_message(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == WAITING_APPEAL
    assert "Invalid log link" in update.effective_message.reply_text.await_args.args[0]


async def test_on_message_submits_appeal_and_ends(monkeypatch) -> None:
    """Valid #appeal message with correct log ref ends the conversation."""
    ba = _ba()
    log_msg_id = 42

    monkeypatch.setattr(appeal_flow.db.bans_db, "set_review", AsyncMock())
    monkeypatch.setattr(appeal_flow.db.bans_db, "set_appeal_log_msg", AsyncMock())
    monkeypatch.setattr(appeal_flow.db.users_cache, "upsert_user", AsyncMock())
    monkeypatch.setattr(
        appeal_flow.parse_logmsg, "appeal_received_log", Mock(return_value="review")
    )
    monkeypatch.setattr(
        appeal_flow.parse_logmsg, "appeal_submitted_log", Mock(return_value="submitted")
    )
    monkeypatch.setattr(appeal_flow, "message_link", Mock(return_value="https://link"))

    text = f"#appeal\nLog link: https://t.me/c/logs/{log_msg_id}\nI'm sorry."
    update = _private_update(uid=99, text=text)
    # * forward returns a message with message_id
    update.effective_message.forward = AsyncMock(
        return_value=SimpleNamespace(message_id=500)
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=888)),
        edit_message_text=AsyncMock(),
    )
    user_data = {
        "appeal_ban_id": "ban1234567x",
        "appeal_log_msg_id": log_msg_id,
        "appeal_instruction_msg_id": 200,
    }
    ctx = _ctx(user_data=user_data, bot=bot)

    result = await ba._on_message(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    # Review post + log sent
    assert bot.send_message.await_count >= 2


# ─────────────────────────── on_decision ────────────────────────────── #


async def test_on_decision_rejects_non_staff(monkeypatch) -> None:
    ba = _ba()
    q = SimpleNamespace(
        data="appeal_approve_ban1234567x",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=50, first_name="Rando"),
    )
    monkeypatch.setattr(
        appeal_flow.db.users_roles, "is_staff", AsyncMock(return_value=False)
    )

    await ba.on_decision(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()))

    q.answer.assert_awaited_once()
    call_kwargs = q.answer.await_args.kwargs
    assert call_kwargs.get("show_alert") is True
    q.edit_message_text.assert_not_awaited()


async def test_on_decision_ban_not_found(monkeypatch) -> None:
    ba = _ba()
    q = SimpleNamespace(
        data="appeal_approve_ban1234567x",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=10, first_name="Staff"),
    )
    monkeypatch.setattr(
        appeal_flow.db.users_roles, "is_staff", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(appeal_flow.db.bans_db, "get_ban", AsyncMock(return_value=None))

    await ba.on_decision(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()))

    q.edit_message_text.assert_awaited_once()
    assert "not found" in q.edit_message_text.await_args.args[0].lower()


async def test_on_decision_already_inactive(monkeypatch) -> None:
    ba = _ba()
    q = SimpleNamespace(
        data="appeal_approve_ban1234567x",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=10, first_name="Staff"),
    )
    monkeypatch.setattr(
        appeal_flow.db.users_roles, "is_staff", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(return_value={"banned_user_id": 99, "is_active": False}),
    )

    await ba.on_decision(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, _ctx()))

    q.edit_message_text.assert_awaited_once()
    assert "already resolved" in q.edit_message_text.await_args.args[0].lower()


async def test_on_decision_approve_deactivates_and_unbans(monkeypatch) -> None:
    """Approve path: ban deactivated, groups unbanned, user notified, card edited."""
    ba = _ba()
    q = SimpleNamespace(
        data="appeal_approve_ban1234567x",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    admin = SimpleNamespace(id=10, first_name="Staff")
    update = SimpleNamespace(callback_query=q, effective_user=admin)

    deactivate = AsyncMock()
    monkeypatch.setattr(
        appeal_flow.db.users_roles, "is_staff", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(
            return_value={
                "banned_user_id": 99,
                "is_active": True,
                "review_timestamp": None,
                "admin_user_id": 10,
                "appeal_log_msg_id": None,
                "appeal_link": "",
                "appeal_submitted_at": None,
            }
        ),
    )
    monkeypatch.setattr(appeal_flow.db.bans_db, "deactivate_ban", deactivate)
    monkeypatch.setattr(
        appeal_flow.db.groups_db,
        "active_groups",
        AsyncMock(return_value=[{"chat_id": -100}]),
    )
    monkeypatch.setattr(
        appeal_flow.db.users_cache,
        "get_first_name",
        AsyncMock(return_value="Target"),
    )
    monkeypatch.setattr(appeal_flow, "fan_out", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        appeal_flow.parse_logmsg, "appeal_approved_edit", Mock(return_value="approved")
    )
    monkeypatch.setattr(
        appeal_flow.parse_logmsg, "appeal_unban_log", Mock(return_value="unban log")
    )

    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        edit_message_text=AsyncMock(),
        unban_chat_member=Mock(),
    )
    ctx = _ctx(bot=bot)

    await ba.on_decision(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    deactivate.assert_awaited_once_with("ban1234567x")
    q.edit_message_text.assert_awaited_once()
    assert "approved" in q.edit_message_text.await_args.args[0].lower()
    # User notified + unban log (at minimum 2 send_message calls)
    assert bot.send_message.await_count >= 2


async def test_on_decision_reject_notifies_user_and_edits_card(monkeypatch) -> None:
    """Reject path: user notified, review card edited, ban stays active."""
    ba = _ba()
    q = SimpleNamespace(
        data="appeal_reject_ban1234567x",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    admin = SimpleNamespace(id=10, first_name="Staff")
    update = SimpleNamespace(callback_query=q, effective_user=admin)

    monkeypatch.setattr(
        appeal_flow.db.users_roles, "is_staff", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        appeal_flow.db.bans_db,
        "get_ban",
        AsyncMock(
            return_value={
                "banned_user_id": 99,
                "is_active": True,
                "review_timestamp": None,
                "admin_user_id": 10,
                "appeal_log_msg_id": None,
                "appeal_link": "",
                "appeal_submitted_at": None,
            }
        ),
    )
    monkeypatch.setattr(
        appeal_flow.db.users_cache,
        "get_first_name",
        AsyncMock(return_value="Target"),
    )
    monkeypatch.setattr(
        appeal_flow.parse_logmsg, "appeal_rejected_edit", Mock(return_value="rejected")
    )

    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        edit_message_text=AsyncMock(),
    )
    ctx = _ctx(bot=bot)

    await ba.on_decision(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    q.edit_message_text.assert_awaited_once()
    assert "rejected" in q.edit_message_text.await_args.args[0].lower()
    # User notified of rejection
    bot.send_message.assert_awaited()
