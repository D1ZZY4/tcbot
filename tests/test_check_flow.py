# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for check_flow: Check class view builders covering profile, bans, warns, kicks, mutes, and appeals."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from tcbot.modules.helper.workflows import check_flow
from tcbot.modules.helper.workflows.check_flow import Check

# ─────────────────────────── Check.profile ──────────────────────── #


async def test_profile_no_ban_no_role(monkeypatch) -> None:
    """Profile renders correctly when user has no active ban and no federation role."""
    monkeypatch.setattr(
        check_flow, "_resolve_user_info", AsyncMock(return_value=("Alice", None))
    )
    monkeypatch.setattr(
        check_flow.db.users_roles,
        "role_meta",
        AsyncMock(return_value=(None, None, None)),
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_ban_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_appeal_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_total_warns", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_warn_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.kicks_db, "user_kick_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.mutes_db, "user_mute_count", AsyncMock(return_value=0)
    )

    bot = Mock()
    bot.id = 999
    text, kb = await Check.profile(bot, 12345)

    assert "Alice" in text
    assert "12345" in text
    assert "Active Ban: No" in text
    assert kb is not None


async def test_profile_with_active_ban(monkeypatch) -> None:
    """Active ban ID appears in the profile text."""
    monkeypatch.setattr(
        check_flow, "_resolve_user_info", AsyncMock(return_value=("Bob", "bob_u"))
    )
    monkeypatch.setattr(
        check_flow.db.users_roles,
        "role_meta",
        AsyncMock(return_value=(None, None, None)),
    )
    monkeypatch.setattr(
        check_flow.db.bans_db,
        "get_active_ban",
        AsyncMock(return_value={"ban_id": "BAN001"}),
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_ban_count", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_appeal_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_total_warns", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_warn_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.kicks_db, "user_kick_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.mutes_db, "user_mute_count", AsyncMock(return_value=0)
    )

    bot = Mock()
    bot.id = 999
    text, kb = await Check.profile(bot, 42)

    assert "BAN001" in text
    assert "Yes" in text


async def test_profile_with_staff_role(monkeypatch) -> None:
    """Staff role label and 'Assigned by' line appear when role_meta returns a role."""
    monkeypatch.setattr(
        check_flow, "_resolve_user_info", AsyncMock(return_value=("StaffUser", None))
    )
    monkeypatch.setattr(
        check_flow.db.users_roles,
        "role_meta",
        AsyncMock(return_value=("admin", 10, None)),
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_ban_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_appeal_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_total_warns", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_warn_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.kicks_db, "user_kick_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.mutes_db, "user_mute_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="Promoter")
    )

    bot = Mock()
    bot.id = 999
    text, kb = await Check.profile(bot, 77)

    assert "Admin" in text
    assert "Assigned by" in text


# ─────────────────────────── Check.bans_list ────────────────────── #


async def test_bans_list_empty(monkeypatch) -> None:
    """Empty ban list returns the no-records message."""
    monkeypatch.setattr(check_flow.db.bans_db, "user_bans", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="User 99")
    )

    text, kb = await Check.bans_list(99, 0)

    assert "No ban records" in text
    assert kb is not None


async def test_bans_list_with_bans(monkeypatch) -> None:
    """Active ban entry shows ban ID, status, and truncated reason."""
    bans = [
        {"ban_id": "BAN1", "is_active": True, "reason": "spamming", "timestamp": None}
    ]
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_bans", AsyncMock(return_value=bans)
    )

    text, kb = await Check.bans_list(99, 0)

    assert "BAN1" in text
    assert "Active" in text
    assert "spamming" in text


# ─────────────────────────── Check.ban_detail ───────────────────── #


async def test_ban_detail_not_found(monkeypatch) -> None:
    """get_ban returning None produces a 'not found' reply."""
    monkeypatch.setattr(check_flow.db.bans_db, "get_ban", AsyncMock(return_value=None))

    text, kb = await Check.ban_detail(99, "MISSING")

    assert "not found" in text.lower()


async def test_ban_detail_wrong_user(monkeypatch) -> None:
    """Ban belonging to a different user ID is treated as not found."""
    monkeypatch.setattr(
        check_flow.db.bans_db,
        "get_ban",
        AsyncMock(return_value={"banned_user_id": 999, "ban_id": "B1"}),
    )

    text, kb = await Check.ban_detail(42, "B1")

    assert "not found" in text.lower()


async def test_ban_detail_found_no_proof(monkeypatch) -> None:
    """Valid ban renders detail text; no proof button when proof_link is None."""
    ban = {"banned_user_id": 42, "ban_id": "B1"}
    monkeypatch.setattr(check_flow.db.bans_db, "get_ban", AsyncMock(return_value=ban))
    monkeypatch.setattr(
        check_flow, "build_ban_detail", AsyncMock(return_value=("Ban text here", None))
    )

    text, kb = await Check.ban_detail(42, "B1")

    assert "Ban text here" in text
    button_labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert not any("Proof" in lbl for lbl in button_labels)


async def test_ban_detail_found_with_proof(monkeypatch) -> None:
    """Proof button appears when build_ban_detail returns a proof link."""
    ban = {"banned_user_id": 42, "ban_id": "B2"}
    monkeypatch.setattr(check_flow.db.bans_db, "get_ban", AsyncMock(return_value=ban))
    monkeypatch.setattr(
        check_flow,
        "build_ban_detail",
        AsyncMock(return_value=("Ban text", "https://t.me/c/1/2")),
    )

    text, kb = await Check.ban_detail(42, "B2")

    button_labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("Proof" in lbl for lbl in button_labels)


# ────────────────────── Check.warns_by_group ────────────────────── #


async def test_warns_by_group_empty(monkeypatch) -> None:
    """No warning groups returns the no-records message."""
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_warn_groups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="User 5")
    )

    text, kb = await Check.warns_by_group(5)

    assert "No warning records" in text


async def test_warns_by_group_with_groups(monkeypatch) -> None:
    """Group title and warn count appear in the by-group summary."""
    monkeypatch.setattr(
        check_flow.db.warns_db, "user_warn_groups", AsyncMock(return_value=[(-1001, 3)])
    )
    monkeypatch.setattr(
        check_flow.db.groups_db,
        "get_group_titles",
        AsyncMock(return_value={-1001: "Main Chat"}),
    )

    text, kb = await Check.warns_by_group(5)

    assert "Main Chat" in text
    assert "3" in text
    assert kb is not None


# ─────────────────────── Check.warns_in_group ───────────────────── #


async def test_warns_in_group_empty(monkeypatch) -> None:
    """No warns in a specific group returns the empty-state message."""
    monkeypatch.setattr(check_flow.db.warns_db, "get_warns", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        check_flow.db.groups_db,
        "get_group_titles",
        AsyncMock(return_value={-1001: "Main Chat"}),
    )

    text, kb = await Check.warns_in_group(5, -1001, 0)

    assert "No warning records" in text


async def test_warns_in_group_with_warns(monkeypatch) -> None:
    """Warns are listed newest-first with reason, group title, and admin name."""
    warns = [{"reason": "flooding", "timestamp": None, "admin_id": 10}]
    monkeypatch.setattr(
        check_flow.db.warns_db, "get_warns", AsyncMock(return_value=warns)
    )
    monkeypatch.setattr(
        check_flow.db.groups_db,
        "get_group_titles",
        AsyncMock(return_value={-1001: "Main Chat"}),
    )
    monkeypatch.setattr(
        check_flow.db.users_cache,
        "get_first_names_batch",
        AsyncMock(return_value={10: "Admin"}),
    )

    text, kb = await Check.warns_in_group(5, -1001, 0)

    assert "flooding" in text
    assert "Main Chat" in text


# ─────────────────────── Check.kicks_list ───────────────────────── #


async def test_kicks_list_empty(monkeypatch) -> None:
    """No kick records returns the no-records message for kicks."""
    monkeypatch.setattr(
        check_flow.db.kicks_db, "user_kicks", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="User 5")
    )

    text, kb = await Check.kicks_list(5, 0)

    assert "No kicks records" in text


async def test_kicks_list_with_records(monkeypatch) -> None:
    """Kick records list shows reason, group title, and pagination header."""
    records = [
        {"chat_id": -1001, "reason": "disruptive", "timestamp": None, "admin_id": 10}
    ]
    monkeypatch.setattr(
        check_flow.db.kicks_db, "user_kicks", AsyncMock(return_value=records)
    )
    monkeypatch.setattr(
        check_flow.db.groups_db,
        "get_group_titles",
        AsyncMock(return_value={-1001: "Test Chat"}),
    )
    monkeypatch.setattr(
        check_flow.db.users_cache,
        "get_first_names_batch",
        AsyncMock(return_value={10: "Admin"}),
    )

    text, kb = await Check.kicks_list(5, 0)

    assert "disruptive" in text
    assert "Test Chat" in text
    assert "1 total" in text


# ─────────────────────── Check.mutes_list ───────────────────────── #


async def test_mutes_list_empty(monkeypatch) -> None:
    """No mute records returns the no-records message for mutes."""
    monkeypatch.setattr(
        check_flow.db.mutes_db, "user_mutes", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="User 5")
    )

    text, kb = await Check.mutes_list(5, 0)

    assert "No mutes records" in text


# ─────────────────────── Check.appeals_list ─────────────────────── #


async def test_appeals_list_no_appeals(monkeypatch) -> None:
    """Bans without appeal_log_msg_id are filtered; empty result gives no-records message."""
    bans = [{"ban_id": "B1", "banned_user_id": 5}]
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_bans", AsyncMock(return_value=bans)
    )
    monkeypatch.setattr(
        check_flow.db.users_cache, "get_first_name", AsyncMock(return_value="User 5")
    )

    text, kb = await Check.appeals_list(5, 0)

    assert "No appeal records" in text


async def test_appeals_list_with_approved_appeal(monkeypatch) -> None:
    """A ban with appeal_log_msg_id set appears; inactive ban shows 'Approved' status."""
    bans = [
        {
            "ban_id": "B1",
            "banned_user_id": 5,
            "appeal_log_msg_id": 123,
            "is_active": False,
            "timestamp": None,
            "appeal_submitted_at": None,
        }
    ]
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_bans", AsyncMock(return_value=bans)
    )

    text, kb = await Check.appeals_list(5, 0)

    assert "B1" in text
    assert "Approved" in text


async def test_appeals_list_pending_appeal(monkeypatch) -> None:
    """An active ban with an appeal shows 'Pending / Rejected' status."""
    bans = [
        {
            "ban_id": "B2",
            "banned_user_id": 5,
            "appeal_log_msg_id": 456,
            "is_active": True,
            "timestamp": None,
            "appeal_submitted_at": None,
        }
    ]
    monkeypatch.setattr(
        check_flow.db.bans_db, "user_bans", AsyncMock(return_value=bans)
    )

    text, kb = await Check.appeals_list(5, 0)

    assert "B2" in text
    assert "Pending" in text
