# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.maintenance - module metadata and pure helpers."""

from __future__ import annotations

from types import SimpleNamespace

import tcbot.modules.maintenance as maintenance
from tcbot.modules.maintenance import _should_remove

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_cleanup() -> None:
    assert maintenance.__module_name__ == "Cleanup"


def test_help_text_is_non_empty() -> None:
    assert isinstance(maintenance.__help_text__, str)
    assert maintenance.__help_text__.strip()


def test_help_sections_is_list_of_tuples() -> None:
    sections = maintenance.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in maintenance.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_leaveall() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "leaveall" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_cleanup() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "cleanup" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_founder() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "Founder" in lookup["Who can use"]


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(maintenance.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_no_emdash() -> None:
    for _key, value in maintenance.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in maintenance.__help_sections__]
    assert len(keys) == len(set(keys))


# ────────────────────── _should_remove pure logic ───────────────── #


async def test_should_remove_returns_false_for_admin_member(monkeypatch) -> None:
    """Bot is still an active admin: should_remove must return False."""
    member = SimpleNamespace(status="administrator")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is False


async def test_should_remove_returns_true_for_kicked_status(monkeypatch) -> None:
    """Bot was kicked: should_remove must return True."""
    member = SimpleNamespace(status="kicked")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_for_left_status(monkeypatch) -> None:
    """Bot shows 'left' status: should_remove must return True."""
    member = SimpleNamespace(status="left")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_on_exception(monkeypatch) -> None:
    """Network error during membership check: should_remove must return True."""

    async def raise_exc(chat_id, uid):
        raise Exception("timeout")

    bot = SimpleNamespace(id=1, get_chat_member=raise_exc)
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is True


async def test_should_remove_returns_true_for_member_status(monkeypatch) -> None:
    """Bot degraded to plain 'member': should_remove must return False (still present)."""
    member = SimpleNamespace(status="member")
    bot = SimpleNamespace(
        id=1,
        get_chat_member=lambda chat_id, uid: _coro(member),
    )
    grp = {"chat_id": -100}

    result = await _should_remove(bot, grp)

    assert result is False


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(maintenance.__handlers__, list)
    assert len(maintenance.__handlers__) >= 2


def test_handlers_are_message_handlers() -> None:
    from telegram.ext import MessageHandler

    for h in maintenance.__handlers__:
        assert isinstance(h, MessageHandler)


# ──────────────────────────── Helpers ───────────────────────────── #


async def _coro(value):
    return value
