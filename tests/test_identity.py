# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.identity - classify, refuse_message, staff_notice."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import tcbot.modules.helper.identity as identity_mod
from tcbot.modules.helper.identity import (
    Identity,
    classify,
    refuse_message,
    staff_notice,
)

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


# ─────────────────────── classify() - helpers ─────────────────────── #


def _patch_db(
    monkeypatch, *, cached_fname: str, username: str | None, role: str | None
) -> None:
    """Patch both DB calls that classify() gathers in parallel."""
    monkeypatch.setattr(
        identity_mod.db.users_cache,
        "get_user_mention_data",
        AsyncMock(return_value=(cached_fname, username)),
    )
    monkeypatch.setattr(
        identity_mod.db.users_roles,
        "get_effective_role",
        AsyncMock(return_value=role),
    )


def _make_bot(bot_id: int = 9999) -> MagicMock:
    bot = MagicMock()
    bot.id = bot_id
    return bot


# ──────────────────── classify() - early returns ───────────────────── #


async def test_classify_self_returns_self_identity(monkeypatch) -> None:
    """When target_id == executor_id the result is always 'self'."""
    _patch_db(monkeypatch, cached_fname="Alice", username="alice", role=None)
    result = await classify(
        _make_bot(), executor_id=42, target_id=42, target_fname="Alice"
    )
    assert result.kind == "self"
    assert result.target_id == 42


async def test_classify_this_bot_returns_this_bot_identity(monkeypatch) -> None:
    """When target_id matches bot.id the result is 'this_bot'."""
    _patch_db(monkeypatch, cached_fname="TcBot", username="tcbot", role=None)
    result = await classify(
        _make_bot(9999), executor_id=1, target_id=9999, target_fname="TcBot"
    )
    assert result.kind == "this_bot"
    assert result.is_bot is True


async def test_classify_telegram_service_returns_telegram_identity(monkeypatch) -> None:
    """target_id == 777000 (Telegram service account) returns 'telegram'."""
    _patch_db(monkeypatch, cached_fname="Telegram", username=None, role=None)
    result = await classify(
        _make_bot(), executor_id=1, target_id=777000, target_fname="Telegram"
    )
    assert result.kind == "telegram"


async def test_classify_other_bot_flag_returns_other_bot_identity(monkeypatch) -> None:
    """target_is_bot=True on an unknown ID returns 'other_bot'."""
    _patch_db(monkeypatch, cached_fname="SomeBot", username="somebot", role=None)
    result = await classify(
        _make_bot(),
        executor_id=1,
        target_id=555,
        target_fname="SomeBot",
        target_is_bot=True,
    )
    assert result.kind == "other_bot"
    assert result.is_bot is True


# ──────────────────── classify() - role-based paths ────────────────── #


async def test_classify_founder_role(monkeypatch) -> None:
    _patch_db(monkeypatch, cached_fname="Owner", username="owner", role="founder")
    result = await classify(
        _make_bot(), executor_id=1, target_id=2, target_fname="Owner"
    )
    assert result.kind == "founder"


async def test_classify_admin_role(monkeypatch) -> None:
    _patch_db(monkeypatch, cached_fname="Admn", username="admn", role="admin")
    result = await classify(_make_bot(), executor_id=1, target_id=3)
    assert result.kind == "admin"


async def test_classify_developer_role(monkeypatch) -> None:
    _patch_db(monkeypatch, cached_fname="Dev", username="dev", role="developer")
    result = await classify(_make_bot(), executor_id=1, target_id=4)
    assert result.kind == "developer"


async def test_classify_tester_role(monkeypatch) -> None:
    _patch_db(monkeypatch, cached_fname="Tst", username="tst", role="tester")
    result = await classify(_make_bot(), executor_id=1, target_id=5)
    assert result.kind == "tester"


async def test_classify_no_role_returns_user(monkeypatch) -> None:
    _patch_db(monkeypatch, cached_fname="Bob", username="bob", role=None)
    result = await classify(_make_bot(), executor_id=1, target_id=6)
    assert result.kind == "user"


# ──────────────────── classify() - fname fallback ──────────────────── #


async def test_classify_uses_cached_fname_when_target_fname_missing(
    monkeypatch,
) -> None:
    """If target_fname is None, the cached first name is used."""
    _patch_db(monkeypatch, cached_fname="CachedName", username="cn", role=None)
    result = await classify(_make_bot(), executor_id=1, target_id=6, target_fname=None)
    assert result.fname == "CachedName"


async def test_classify_uses_cached_fname_when_target_fname_is_placeholder(
    monkeypatch,
) -> None:
    """If target_fname starts with 'User ', the cached name overrides it."""
    _patch_db(monkeypatch, cached_fname="RealName", username="rn", role=None)
    result = await classify(
        _make_bot(), executor_id=1, target_id=6, target_fname="User 6"
    )
    assert result.fname == "RealName"


async def test_classify_uses_provided_fname_over_cache(monkeypatch) -> None:
    """An explicit, non-placeholder target_fname is kept as-is."""
    _patch_db(monkeypatch, cached_fname="CachedName", username="cn", role=None)
    result = await classify(
        _make_bot(), executor_id=1, target_id=6, target_fname="Provided"
    )
    assert result.fname == "Provided"


# ─────────── classify() - both DB calls are actually invoked ─────────── #


async def test_classify_gather_invokes_both_db_calls(monkeypatch) -> None:
    """Both get_user_mention_data and get_effective_role must be called (parallel gather)."""
    mention_mock = AsyncMock(return_value=("N", "n"))
    role_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        identity_mod.db.users_cache, "get_user_mention_data", mention_mock
    )
    monkeypatch.setattr(identity_mod.db.users_roles, "get_effective_role", role_mock)
    await classify(_make_bot(), executor_id=1, target_id=7)
    mention_mock.assert_called_once_with(7)
    role_mock.assert_called_once_with(7)


# ─────────────────────────── role_label ──────────────────────────── #


def test_role_label_founder_returns_correct_label() -> None:
    """Founder identity returns the public-facing 'Founder' label."""
    ident = Identity("founder", 1, "Alice", None)
    assert ident.role_label == "Founder"


def test_role_label_admin_returns_correct_label() -> None:
    """Admin identity returns the public-facing 'Admin' label."""
    ident = Identity("admin", 2, "Bob", None)
    assert ident.role_label == "Admin"


def test_role_label_developer_returns_correct_label() -> None:
    """Developer identity returns the public-facing 'Developer' label."""
    ident = Identity("developer", 3, "Carol", None)
    assert ident.role_label == "Developer"


def test_role_label_tester_returns_correct_label() -> None:
    """Tester identity returns the public-facing 'Tester' label."""
    ident = Identity("tester", 4, "Dave", None)
    assert ident.role_label == "Tester"


def test_role_label_regular_user_returns_none() -> None:
    """Non-staff identity returns None - users have no public role label."""
    ident = Identity("user", 5, "Eve", None)
    assert ident.role_label is None


def test_role_label_telegram_service_returns_none() -> None:
    """Telegram service account has no public role label."""
    ident = Identity("telegram", 777000, "Telegram", None)
    assert ident.role_label is None


def test_role_label_self_kind_returns_none() -> None:
    """'self' identity (executor targeting themselves) has no public role label."""
    ident = Identity("self", 1, "Alice", None)
    assert ident.role_label is None
