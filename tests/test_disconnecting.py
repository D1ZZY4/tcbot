# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.disconnecting - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.disconnecting as disconnecting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_disconnect() -> None:
    assert disconnecting.__module_name__ == "Disconnect"


def test_help_text_is_non_empty() -> None:
    assert isinstance(disconnecting.__help_text__, str)
    assert disconnecting.__help_text__.strip()


def test_help_text_mentions_tcdisconnect() -> None:
    assert "tcdisconnect" in disconnecting.__help_text__


def test_help_text_mentions_rmtc() -> None:
    assert "rmtc" in disconnecting.__help_text__


def test_help_sections_is_list_of_tuples() -> None:
    sections = disconnecting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in disconnecting.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcdisconnect() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "tcdisconnect" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_rmtc() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "rmtc" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(disconnecting.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_no_emdash() -> None:
    for _key, value in disconnecting.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in disconnecting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_has_two_entries() -> None:
    assert isinstance(disconnecting.__handlers__, list)
    assert len(disconnecting.__handlers__) == 2


def test_handlers_are_message_handlers() -> None:
    from telegram.ext import MessageHandler

    for h in disconnecting.__handlers__:
        assert isinstance(h, MessageHandler)
