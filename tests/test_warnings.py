# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.warnings - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.warnings as warnings

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_warnings() -> None:
    assert warnings.__module_name__ == "Warnings"


def test_help_text_is_non_empty() -> None:
    assert isinstance(warnings.__help_text__, str)
    assert warnings.__help_text__.strip()


def test_help_text_mentions_warn() -> None:
    assert "warn" in warnings.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = warnings.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in warnings.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcwarn() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "tcwarn" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcunwarn() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "tcunwarn" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_warns() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "warns" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_resetwarns() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "resetwarns" in lookup["Commands & Aliases"]


def test_help_sections_contains_flow() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Flow (/tcwarn)" in keys


def test_help_sections_contains_target_syntax() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert "Target syntax" in keys


def test_help_sections_what_it_does_mentions_per_group() -> None:
    lookup = dict(warnings.__help_sections__)
    assert "per-group" in lookup["What it does"].lower()


def test_help_sections_who_can_use_distinguishes_roles() -> None:
    lookup = dict(warnings.__help_sections__)
    who = lookup["Who can use"]
    assert "Tester" in who
    assert "anyone" in who.lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in warnings.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in warnings.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(warnings.__handlers__, list)
    assert len(warnings.__handlers__) >= 2
