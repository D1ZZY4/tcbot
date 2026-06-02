# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.muting - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.muting as muting

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_mute() -> None:
    assert muting.__module_name__ == "Mute"


def test_help_text_is_non_empty() -> None:
    assert isinstance(muting.__help_text__, str)
    assert muting.__help_text__.strip()


def test_help_text_mentions_mute() -> None:
    assert "mute" in muting.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = muting.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in muting.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcmute() -> None:
    lookup = dict(muting.__help_sections__)
    assert "tcmute" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunmute() -> None:
    lookup = dict(muting.__help_sections__)
    assert "tcunmute" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcm_alias() -> None:
    lookup = dict(muting.__help_sections__)
    assert "/tcm" in lookup["Commands & Aliases"]


def test_help_sections_contains_time_format() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Time format" in keys


def test_help_sections_time_format_mentions_duration_units() -> None:
    lookup = dict(muting.__help_sections__)
    for unit_code in ("s", "m", "h", "d", "w"):
        assert unit_code in lookup["Time format"]


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_no_emdash() -> None:
    for _key, value in muting.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in muting.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(muting.__handlers__, list)
    assert len(muting.__handlers__) >= 1
