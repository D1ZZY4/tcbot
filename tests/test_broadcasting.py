# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.broadcasting - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.broadcasting as broadcasting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_broadcast() -> None:
    assert broadcasting.__module_name__ == "Broadcast"


def test_help_text_is_non_empty() -> None:
    assert isinstance(broadcasting.__help_text__, str)
    assert broadcasting.__help_text__.strip()


def test_help_sections_is_list_of_tuples() -> None:
    sections = broadcasting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in broadcasting.__help_sections__:
        assert isinstance(key, str) and key.strip(), f"Empty key found: {key!r}"
        assert isinstance(value, str) and value.strip(), f"Empty value for key {key!r}"


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_who_can_use_references_staff() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "Staff" in lookup["Who can use"]


def test_help_sections_commands_mentions_tcbroadcast() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "tcbroadcast" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_bc_alias() -> None:
    lookup = dict(broadcasting.__help_sections__)
    assert "/bc" in lookup["Commands & Aliases"]


def test_help_sections_no_emoji_or_emdash() -> None:
    for _key, value in broadcasting.__help_sections__:
        assert "\u2014" not in value, f"Em-dash found in section value: {value!r}"


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in broadcasting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(broadcasting.__handlers__, list)
    assert len(broadcasting.__handlers__) > 0


def test_handlers_contains_message_handler() -> None:
    types = [type(h).__name__ for h in broadcasting.__handlers__]
    assert "MessageHandler" in types
