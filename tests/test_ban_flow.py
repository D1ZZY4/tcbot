# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Regression tests for the ban update workflow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tcbot.modules.helper.workflows import ban_flow


def _message(message_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(message_id=message_id)


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
    monkeypatch.setattr(ban_flow.db.users_db, "get_first_name", get_first_name)
    monkeypatch.setattr(ban_flow.db.users_db, "upsert_user", upsert_user)
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
