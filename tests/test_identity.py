# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.identity - refuse_message and staff_notice."""

from __future__ import annotations

from tcbot.modules.helper.identity import Identity, refuse_message, staff_notice

# ──────────────────── refuse_message - basic ───────────────────── #


def test_refuse_message_self_ban_returns_non_empty() -> None:
    ident = Identity("self", 1, "Alice", None)
    result = refuse_message("ban", ident)
    assert result is not None
    assert result.strip()


def test_refuse_message_user_ban_returns_none() -> None:
    """Regular users can be banned - no refusal."""
    ident = Identity("user", 3, "Charlie", None)
    assert refuse_message("ban", ident) is None


def test_refuse_message_unknown_action_returns_none() -> None:
    ident = Identity("self", 1, "Alice", None)
    assert refuse_message("nonexistent_action", ident) is None


def test_refuse_message_other_bot_ban_returns_none() -> None:
    """other_bot is not blocked from being banned."""
    ident = Identity("other_bot", 9, "SomeBot", "somebot", is_bot=True)
    assert refuse_message("ban", ident) is None


# ───────────────── refuse_message - line interpolation ─────────── #


def test_refuse_message_line_placeholder_resolved() -> None:
    """Refusal strings that contain {line} must resolve - no literal {line} in output."""
    ident = Identity("founder", 99, "Owen", "owen")
    result = refuse_message("ban", ident)
    assert result is not None
    assert "{line}" not in result


def test_refuse_message_founder_name_in_output() -> None:
    """The founder's name should appear when {line} is expanded."""
    ident = Identity("founder", 2, "Bob", "bob")
    result = refuse_message("ban", ident)
    assert result is not None
    assert "Bob" in result


def test_refuse_message_self_no_line_interpolation_needed() -> None:
    """self refusals have no {line}; they must still return a plain string."""
    ident = Identity("self", 1, "Me", None)
    result = refuse_message("kick", ident)
    assert result is not None
    assert "{line}" not in result


# ──────────────── refuse_message - all actions block self ──────── #


def test_all_actions_block_self() -> None:
    """Every known action must refuse when the executor targets themselves."""
    known_actions = [
        "ban",
        "kick",
        "mute",
        "warn",
        "unban",
        "unmute",
        "promote",
        "demote",
        "transfer",
        "unwarn",
        "resetwarns",
    ]
    ident = Identity("self", 1, "Me", None)
    for action in known_actions:
        result = refuse_message(action, ident)
        assert result is not None, f"action={action!r} should refuse against self"


# ──────────────── refuse_message - this_bot always blocked ─────── #


def test_this_bot_blocked_for_ban_kick_mute() -> None:
    ident = Identity("this_bot", 0, "Bot", None, is_bot=True)
    for action in ("ban", "kick", "mute", "warn"):
        assert refuse_message(action, ident) is not None, (
            f"action={action!r} should refuse against this_bot"
        )


# ──────────────── refuse_message - user / user-rank free ────────── #


def test_regular_user_allowed_for_all_mod_actions() -> None:
    """user identity should never produce a refusal for moderation commands."""
    ident = Identity("user", 7, "Target", "target")
    for action in ("ban", "kick", "mute", "warn", "unwarn", "resetwarns"):
        assert refuse_message(action, ident) is None, (
            f"action={action!r} should allow regular user"
        )


# ──────────────────── refuse_message - staff targets ───────────── #


def test_admin_blocked_from_ban_without_demote() -> None:
    ident = Identity("admin", 5, "Admin", "admin_user")
    result = refuse_message("ban", ident)
    assert result is not None
    assert "Demote" in result or "demote" in result


def test_tester_blocked_from_kick_without_demote() -> None:
    ident = Identity("tester", 6, "Tester", "tester_user")
    result = refuse_message("kick", ident)
    assert result is not None


def test_telegram_service_account_blocked() -> None:
    ident = Identity("telegram", 777000, "Telegram", None)
    assert refuse_message("ban", ident) is not None
    assert refuse_message("kick", ident) is not None


# ─────────────────────── staff_notice ──────────────────────────── #


def test_staff_notice_admin_returns_heads_up() -> None:
    ident = Identity("admin", 5, "Dave", "dave")
    result = staff_notice("unwarn", ident, "Test Federation")
    assert result is not None
    assert "Dave" in result


def test_staff_notice_developer_includes_community_name() -> None:
    ident = Identity("developer", 8, "Dev", "devguy")
    result = staff_notice("mute", ident, "Community X")
    assert result is not None
    assert "Community X" in result


def test_staff_notice_tester_returns_heads_up() -> None:
    ident = Identity("tester", 11, "Tester", "testeruser")
    result = staff_notice("resetwarns", ident, "FedName")
    assert result is not None


def test_staff_notice_regular_user_returns_none() -> None:
    ident = Identity("user", 6, "Eve", None)
    assert staff_notice("unwarn", ident, "Test Federation") is None


def test_staff_notice_founder_returns_none() -> None:
    """Founder is not in the heads-up set (admin/developer/tester only)."""
    ident = Identity("founder", 7, "Owner", None)
    assert staff_notice("ban", ident, "Test Federation") is None


def test_staff_notice_self_returns_none() -> None:
    ident = Identity("self", 1, "Me", None)
    assert staff_notice("ban", ident, "Test Federation") is None


def test_staff_notice_this_bot_returns_none() -> None:
    ident = Identity("this_bot", 0, "Bot", None, is_bot=True)
    assert staff_notice("ban", ident, "Test Federation") is None


def test_staff_notice_action_present_in_output() -> None:
    """The proceeding action should appear in the heads-up text."""
    ident = Identity("admin", 5, "Dave", "dave")
    result = staff_notice("unmute", ident, "FedX")
    assert result is not None
    assert "unmute" in result
