# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Regression and state-machine tests for the ban workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper.workflows import ban_flow


def _message(
    message_id: int = 1, *, media_group_id: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(message_id=message_id, media_group_id=media_group_id)


def _fake_ctx(user_data: dict | None = None, bot=None) -> SimpleNamespace:
    return SimpleNamespace(
        bot=bot or SimpleNamespace(),
        user_data=user_data if user_data is not None else {},
    )


# ───────────────────── _execute_ban: update path ────────────────────── #


async def test_execute_ban_update_preserves_previous_ids_and_username_fallback(
    monkeypatch,
) -> None:
    existing = {
        "ban_id": "ban1234567",
        "admin_user_id": 777,
        "proof_message_id": 55,
        "log_message_id": 66,
        "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    bot = SimpleNamespace(
        username=None,
        send_message=AsyncMock(side_effect=RuntimeError("log send failed")),
    )
    update_ban = AsyncMock(return_value=existing)
    set_log_message_id = AsyncMock()
    active_groups = AsyncMock(return_value=[])
    get_first_name = AsyncMock(return_value="Old Admin")
    upsert_user = AsyncMock()

    monkeypatch.setattr(
        ban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=existing)
    )
    monkeypatch.setattr(ban_flow.db.bans_db, "update_ban", update_ban)
    monkeypatch.setattr(ban_flow.db.bans_db, "set_log_message_id", set_log_message_id)
    monkeypatch.setattr(ban_flow.db.groups_db, "active_groups", active_groups)
    monkeypatch.setattr(ban_flow.db.users_cache, "get_first_name", get_first_name)
    monkeypatch.setattr(ban_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(ban_flow, "upload_proof", AsyncMock(return_value=None))
    monkeypatch.setattr(ban_flow, "fan_out", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        ban_flow.parse_logmsg, "ban_update_log", Mock(return_value="log")
    )
    monkeypatch.setattr(ban_flow.keyboards, "ban_log_update", Mock(return_value=None))
    monkeypatch.setattr(ban_flow.keyboards, "ban_log_new", Mock(return_value=None))

    seen: dict[str, str] = {}

    def fake_appeal_deep_link(username: str, ban_id: str) -> str:
        seen["username"] = username
        seen["ban_id"] = ban_id
        return f"https://t.me/{username}?start=appeal_{ban_id}"

    monkeypatch.setattr(ban_flow, "appeal_deep_link", fake_appeal_deep_link)

    await ban_flow._execute_ban(
        bot,
        [_message()],
        {
            "ban_target_id": 42,
            "ban_target_fname": "Target",
            "ban_reason": "spam",
            "ban_admin_id": 999,
            "ban_admin_fname": "Admin",
            "ban_prompt_msg_id": 0,
            "ban_prompt_chat_id": 0,
        },
    )

    assert seen["username"] == "TCFBot"
    assert seen["ban_id"] == "ban1234567"
    assert update_ban.await_args.args[3:] == (55, 66, 55, 66)
    set_log_message_id.assert_not_awaited()


# ────────────────────── _execute_ban: new ban path ──────────────────── #


async def test_execute_ban_new_creates_ban_log_and_enforces_fan_out(
    monkeypatch,
) -> None:
    """New-ban happy path: create_ban called, log posted, fan_out enforced."""
    bot = SimpleNamespace(
        username="TestBot",
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
        ban_chat_member=Mock(),
        edit_message_text=AsyncMock(),
    )
    create_ban = AsyncMock()
    set_log_message_id = AsyncMock()
    upsert_user = AsyncMock()
    fan_out_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(
        ban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        ban_flow.db.bans_db, "make_ban_id", Mock(return_value="newban1234")
    )
    monkeypatch.setattr(ban_flow.db.bans_db, "create_ban", create_ban)
    monkeypatch.setattr(ban_flow.db.bans_db, "set_log_message_id", set_log_message_id)
    monkeypatch.setattr(
        ban_flow.db.groups_db,
        "active_groups",
        AsyncMock(return_value=[{"chat_id": -100}]),
    )
    monkeypatch.setattr(ban_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(ban_flow, "upload_proof", AsyncMock(return_value=None))
    monkeypatch.setattr(ban_flow, "fan_out", fan_out_mock)
    monkeypatch.setattr(
        ban_flow.parse_logmsg, "proof_caption_new", Mock(return_value="cap")
    )
    monkeypatch.setattr(ban_flow.parse_logmsg, "ban_log", Mock(return_value="log text"))
    monkeypatch.setattr(ban_flow.keyboards, "ban_log_new", Mock(return_value=None))
    monkeypatch.setattr(
        ban_flow, "appeal_deep_link", Mock(return_value="https://t.me/...")
    )
    monkeypatch.setattr(ban_flow, "message_link", Mock(return_value="https://link"))

    await ban_flow._execute_ban(
        bot,
        [_message()],
        {
            "ban_target_id": 55,
            "ban_target_fname": "Target",
            "ban_reason": "flood",
            "ban_admin_id": 10,
            "ban_admin_fname": "Admin",
            "ban_prompt_msg_id": 5,
            "ban_prompt_chat_id": -100,
        },
    )

    create_ban.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    # Log message_id=77 was returned, so set_log_message_id must be called
    set_log_message_id.assert_awaited_once()
    fan_out_mock.assert_awaited_once()
    # Prompt edit issued (prompt_msg_id and prompt_chat_id are set)
    bot.edit_message_text.assert_awaited_once()
    upsert_user.assert_awaited_once()


async def test_execute_ban_new_log_failure_skips_set_log_message_id(
    monkeypatch,
) -> None:
    """When send_message raises, log_msg_id stays 0 and set_log_message_id is skipped."""
    bot = SimpleNamespace(
        username="TestBot",
        send_message=AsyncMock(side_effect=RuntimeError("network error")),
        ban_chat_member=Mock(),
    )
    create_ban = AsyncMock()
    set_log_message_id = AsyncMock()
    upsert_user = AsyncMock()

    monkeypatch.setattr(
        ban_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        ban_flow.db.bans_db, "make_ban_id", Mock(return_value="failban123")
    )
    monkeypatch.setattr(ban_flow.db.bans_db, "create_ban", create_ban)
    monkeypatch.setattr(ban_flow.db.bans_db, "set_log_message_id", set_log_message_id)
    monkeypatch.setattr(
        ban_flow.db.groups_db, "active_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(ban_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(ban_flow, "upload_proof", AsyncMock(return_value=None))
    monkeypatch.setattr(ban_flow, "fan_out", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        ban_flow.parse_logmsg, "proof_caption_new", Mock(return_value="cap")
    )
    monkeypatch.setattr(ban_flow.parse_logmsg, "ban_log", Mock(return_value="log"))
    monkeypatch.setattr(ban_flow.keyboards, "ban_log_new", Mock(return_value=None))
    monkeypatch.setattr(
        ban_flow, "appeal_deep_link", Mock(return_value="https://t.me/...")
    )

    await ban_flow._execute_ban(
        bot,
        [_message()],
        {
            "ban_target_id": 55,
            "ban_target_fname": "Target",
            "ban_reason": "spam",
            "ban_admin_id": 10,
            "ban_admin_fname": "Admin",
            "ban_prompt_msg_id": 0,
            "ban_prompt_chat_id": 0,
        },
    )

    create_ban.assert_awaited_once()
    # Log send failed: set_log_message_id must NOT be called
    set_log_message_id.assert_not_awaited()


# ──────────────────── ConversationHandler step handlers ─────────────── #


async def test_on_proof_received_single_media_calls_execute_and_ends(
    monkeypatch,
) -> None:
    """A single non-album photo resolves immediately and ends the conversation."""
    execute = AsyncMock()
    monkeypatch.setattr(ban_flow, "_execute_ban", execute)

    msg = _message(media_group_id=None)
    update = SimpleNamespace(effective_message=msg)
    ctx = _fake_ctx(user_data={"ban_target_id": 1}, bot=SimpleNamespace())

    result = await ban_flow.on_proof_received(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    execute.assert_awaited_once()
    call_args = execute.await_args
    # Second argument is [msg]
    assert call_args.args[1] == [msg]


async def test_on_proof_received_album_first_message_returns_waiting(
    monkeypatch,
) -> None:
    """First message of an album is buffered; conversation stays open."""
    # Patch _flush_album to prevent the real sleep / executor
    monkeypatch.setattr(ban_flow, "_flush_album", AsyncMock())

    # Clean album state before test to avoid cross-test leakage
    ban_flow._albums.clear()
    ban_flow._album_meta.clear()

    msg = _message(media_group_id="album-001")
    update = SimpleNamespace(effective_message=msg)
    ctx = _fake_ctx(user_data={"ban_target_id": 1}, bot=SimpleNamespace())

    result = await ban_flow.on_proof_received(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ban_flow.WAITING_PROOF
    assert "album-001" in ban_flow._albums
    assert msg in ban_flow._albums["album-001"]

    # Clean up after test
    ban_flow._albums.clear()
    ban_flow._album_meta.clear()


async def test_on_cancel_proof_answers_edits_and_ends() -> None:
    """Cancel button answers the query, edits the message, and ends the conversation."""
    q = SimpleNamespace(
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)
    ctx = _fake_ctx()

    result = await ban_flow.on_cancel_proof(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    q.answer.assert_awaited_once()
    q.edit_message_text.assert_awaited_once()
    edited_text = q.edit_message_text.await_args.args[0]
    assert "Cancelled" in edited_text


async def test_on_proof_timeout_with_message_replies_and_ends() -> None:
    """Timeout sends a reply when effective_message is present."""
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_message=msg)
    ctx = _fake_ctx()

    result = await ban_flow.on_proof_timeout(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    msg.reply_text.assert_awaited_once()
    assert "Timed out" in msg.reply_text.await_args.args[0]


async def test_on_proof_timeout_without_message_ends_silently() -> None:
    """Timeout with no effective_message does not raise and still ends."""
    update = SimpleNamespace(effective_message=None)
    ctx = _fake_ctx()

    result = await ban_flow.on_proof_timeout(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
