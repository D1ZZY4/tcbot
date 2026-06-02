# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.kicking - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.kicking as kicking

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_kick() -> None:
    assert kicking.__module_name__ == "Kick"


def test_help_text_is_non_empty() -> None:
    assert isinstance(kicking.__help_text__, str)
    assert kicking.__help_text__.strip()


def test_help_text_mentions_group() -> None:
    assert "group" in kicking.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = kicking.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in kicking.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tckick() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "tckick" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tck_alias() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "/tck" in lookup["Commands & Aliases"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_contains_flow() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert "Flow" in keys


def test_help_sections_what_it_does_mentions_group_only() -> None:
    lookup = dict(kicking.__help_sections__)
    assert "group" in lookup["What it does"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in kicking.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in kicking.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(kicking.__handlers__, list)
    assert len(kicking.__handlers__) >= 1
