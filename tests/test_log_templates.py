# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.parse_logmsg."""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot import cfg
from tcbot.modules.helper import parse_logmsg

# ───────────────────────────── Helpers ──────────────────────────── #


def _community_present(text: str) -> bool:
    return cfg.community_name in text


# ──────────────────────────── Ban logs ──────────────────────────── #


def test_ban_log_contains_community_and_key_fields() -> None:
    ts = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    out = parse_logmsg.ban_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        reason="Spamming links",
        ban_id="ban_2_1",
        timestamp=ts,
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Spamming links" in out
    assert "Commit at: 30-04-2026 | 12:00" in out


def test_ban_log_without_proof_link_has_no_href() -> None:
    out = parse_logmsg.ban_log(
        target_id=2,
        target_fname="X",
        admin_id=1,
        admin_fname="Y",
        reason="R",
        ban_id="b",
        proof_lnk=None,
    )
    # * Proof access is now provided by the inline keyboard button, not a hyperlink.
    assert "View Proof" not in out


def test_ban_log_with_proof_link_has_no_inline_link() -> None:
    """The ban_log text never embeds a hyperlink — the keyboard's Proof button covers it."""
    out = parse_logmsg.ban_log(
        target_id=2,
        target_fname="X",
        admin_id=1,
        admin_fname="Y",
        reason="R",
        ban_id="b",
        proof_lnk="https://t.me/c/1234/5",
    )
    assert "View Proof" not in out
    assert "https://t.me/c/1234/5" not in out


# ──────────────────────────── Unban log ─────────────────────────── #


def test_unban_log_without_reason_has_no_reason_line() -> None:
    out = parse_logmsg.unban_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        ban_id="b",
    )
    assert _community_present(out)
    assert "Unban Reason:" not in out


def test_unban_log_with_reason_includes_reason() -> None:
    out = parse_logmsg.unban_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        ban_id="b",
        reason="Appeal Approved",
    )
    assert "Unban Reason: Appeal Approved" in out


# ───────────────────────── Proof captions ───────────────────────── #


def test_proof_caption_new_includes_admin_and_timestamp() -> None:
    ts = datetime(2026, 4, 30, 12, 30, tzinfo=timezone.utc)
    out = parse_logmsg.proof_caption_new(
        target_id=2,
        admin_id=1,
        admin_fname="Andi",
        timestamp=ts,
    )
    assert "ID: 2" in out
    assert "Admin ID: 1" in out
    assert "Commit at: 30-04-2026 | 12:30" in out


# ────────────────────── Admin management logs ───────────────────── #


def test_admin_promoted_contains_community_and_both_ids() -> None:
    out = parse_logmsg.promoted(
        target_id=2,
        target_fname="Citra",
        role="admin",
        by_id=1,
        by_fname="Andi",
    )
    assert _community_present(out)
    assert "ID: 2" in out and "ID: 1" in out


def test_admin_demoted_contains_community() -> None:
    out = parse_logmsg.demoted(
        target_id=2,
        target_fname="Citra",
        role="admin",
        by_id=1,
        by_fname="Andi",
    )
    assert _community_present(out)
    assert "Citra" in out and "Andi" in out


def test_promoted_uses_unified_title() -> None:
    out = parse_logmsg.promoted(
        target_id=2,
        target_fname="Citra",
        role="developer",
        by_id=1,
        by_fname="Andi",
    )
    # * Title is unified, role moves to a field below the user.
    assert f"New {cfg.community_name} Promoted" in out
    assert "Role: Developer" in out
    assert "Promoted by:" in out


def test_demoted_unified_for_manual_and_trigger() -> None:
    manual = parse_logmsg.demoted(
        target_id=2,
        target_fname="Citra",
        role="tester",
        by_id=1,
        by_fname="Andi",
    )
    auto = parse_logmsg.demoted(
        target_id=2,
        target_fname="Citra",
        role="tester",
        by_id=1,
        by_fname="Andi",
        trigger="ban",
    )
    # * Both call sites produce the same unified shape — no Auto-Demote title.
    assert f"{cfg.community_name} Demoted" in manual
    assert f"{cfg.community_name} Demoted" in auto
    assert "Auto-Demote" not in manual
    assert "Auto-Demote" not in auto
    assert "Role removed: Tester" in manual and "Role removed: Tester" in auto


def test_ownership_transferred_shows_new_and_previous_owner() -> None:
    out = parse_logmsg.ownership_transferred(
        new_owner_id=2,
        new_owner_fname="Citra",
        old_owner_id=1,
        old_owner_fname="Andi",
    )
    assert _community_present(out)
    assert "New Owner" in out and "Previous Owner" in out


# ─────────────────────────── Appeal logs ────────────────────────── #


def test_appeal_submitted_log_contains_ban_id_and_community() -> None:
    out = parse_logmsg.appeal_submitted_log(
        target_id=2,
        target_fname="Citra",
        ban_id="ban_2_1714",
        appeal_link="https://t.me/c/1234/56?thread=12",
    )
    assert _community_present(out)
    assert "ban_2_1714" in out
    assert "https://t.me/c/1234/56?thread=12" in out


def test_appeal_received_log_includes_ban_id_and_user() -> None:
    out = parse_logmsg.appeal_received_log(
        target_id=2,
        target_fname="Citra",
        ban_id="ban_2_1714",
        appeal_link="https://t.me/c/1234/56",
    )
    assert "ban_2_1714" in out
    assert "Citra" in out


# ────────────────────────── Broadcast log ───────────────────────── #


def test_broadcast_log_truncates_preview_at_100_chars() -> None:
    long_text = "x" * 500
    out = parse_logmsg.broadcast_log(
        admin_id=1,
        admin_fname="Andi",
        message_preview=long_text,
        success=10,
        failed=1,
    )
    assert _community_present(out)
    assert "x" * 100 in out
    assert "x" * 101 not in out


# ──────────────────────────── Kick log ──────────────────────────── #


def test_kick_log_contains_community_and_key_fields() -> None:
    out = parse_logmsg.kick_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        reason="Raid participant",
        chat_id=-1001234567890,
        chat_title="Infinix Indonesia",
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Andi" in out
    assert "Raid participant" in out
    assert "Infinix Indonesia" in out
    assert "-1001234567890" in out


def test_kick_log_shows_user_id() -> None:
    out = parse_logmsg.kick_log(
        target_id=99,
        target_fname="X",
        admin_id=1,
        admin_fname="Y",
        reason="R",
        chat_id=-100,
        chat_title="G",
    )
    assert "User ID: 99" in out


# ──────────────────────────── Warn log ──────────────────────────── #


def test_warn_log_contains_community_and_count() -> None:
    out = parse_logmsg.warn_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        reason="Off-topic",
        count=2,
        warn_limit=3,
        chat_id=-1001234567890,
        chat_title="Infinix Indonesia",
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Off-topic" in out
    assert "2/3" in out
    assert "Infinix Indonesia" in out


def test_warn_log_at_limit_shows_correct_count() -> None:
    out = parse_logmsg.warn_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        reason="Final warning",
        count=3,
        warn_limit=3,
        chat_id=-100,
        chat_title="G",
    )
    assert "3/3" in out


# ─────────────────────────── Unwarn log ─────────────────────────── #


def test_unwarn_log_contains_community_and_new_count() -> None:
    out = parse_logmsg.unwarn_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        new_count=1,
        warn_limit=3,
        chat_id=-1001234567890,
        chat_title="Infinix Indonesia",
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Andi" in out
    assert "1/3" in out
    assert "Infinix Indonesia" in out


def test_unwarn_log_at_zero_shows_zero_count() -> None:
    out = parse_logmsg.unwarn_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        new_count=0,
        warn_limit=3,
        chat_id=-100,
        chat_title="G",
    )
    assert "0/3" in out
    assert "User ID: 2" in out


# * Mute / unmute logs ───────────────────────────────────────────────────────────────


def test_mute_log_contains_community_and_key_fields() -> None:
    out = parse_logmsg.mute_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
        reason="Spamming stickers",
        duration_str="3d",
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Andi" in out
    assert "Spamming stickers" in out
    assert "3d" in out
    assert "2" in out


def test_mute_log_permanent_duration() -> None:
    out = parse_logmsg.mute_log(
        target_id=3,
        target_fname="Budi",
        admin_id=1,
        admin_fname="Andi",
        reason="Harassment",
        duration_str="permanently",
    )
    assert "permanently" in out


def test_unmute_log_contains_community_and_both_users() -> None:
    out = parse_logmsg.unmute_log(
        target_id=2,
        target_fname="Citra",
        admin_id=1,
        admin_fname="Andi",
    )
    assert _community_present(out)
    assert "Citra" in out
    assert "Andi" in out
    assert "User ID: 2" in out


# ─────────────────────────── Group logs ─────────────────────────── #


def test_group_connected_log_contains_community_title_and_id() -> None:
    out = parse_logmsg.group_connected_log(
        chat_id=-1001234567890,
        chat_title="Infinix Indonesia",
        owner_id=1,
        owner_fname="Andi",
    )
    assert _community_present(out)
    assert "Infinix Indonesia" in out
    assert "-1001234567890" in out
