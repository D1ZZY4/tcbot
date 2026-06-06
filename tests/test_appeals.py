# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.appeals - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.appeals as appeals

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_appeal() -> None:
    assert appeals.__module_name__ == "Appeal"


def test_help_text_is_non_empty() -> None:
    assert isinstance(appeals.__help_text__, str)
    assert appeals.__help_text__.strip()


def test_help_sections_is_list_of_tuples() -> None:
    sections = appeals.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in appeals.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in appeals.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_who_can_use_mentions_ban() -> None:
    lookup = dict(appeals.__help_sections__)
    assert "ban" in lookup["Who can use"].lower()


def test_help_sections_contains_how_it_works() -> None:
    keys = [k for k, _ in appeals.__help_sections__]
    assert "How it works" in keys


def test_help_sections_how_it_works_mentions_appeal_hash() -> None:
    lookup = dict(appeals.__help_sections__)
    assert "#appeal" in lookup["How it works"]


def test_help_sections_contains_what_happens_next() -> None:
    keys = [k for k, _ in appeals.__help_sections__]
    assert "What happens next" in keys


def test_help_sections_what_happens_next_mentions_approved() -> None:
    lookup = dict(appeals.__help_sections__)
    assert "approved" in lookup["What happens next"].lower()


def test_help_sections_no_emdash() -> None:
    for _key, value in appeals.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in appeals.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(appeals.__handlers__, list)
    assert len(appeals.__handlers__) >= 1
