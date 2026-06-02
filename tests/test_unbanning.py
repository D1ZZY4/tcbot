# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.unbanning - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.unbanning as unbanning

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_unban() -> None:
    assert unbanning.__module_name__ == "Unban"


def test_help_text_is_non_empty() -> None:
    assert isinstance(unbanning.__help_text__, str)
    assert unbanning.__help_text__.strip()


def test_help_text_mentions_federation_ban() -> None:
    assert "federation ban" in unbanning.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = unbanning.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in unbanning.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcunban() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "tcunban" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunb_alias() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "tcunb" in lookup["Commands & Aliases"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_what_it_does_mentions_all_groups() -> None:
    lookup = dict(unbanning.__help_sections__)
    assert "all connected groups" in lookup["What it does"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in unbanning.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in unbanning.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(unbanning.__handlers__, list)
    assert len(unbanning.__handlers__) >= 1
