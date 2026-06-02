# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.help - help content builder and module-level state."""

from __future__ import annotations

import re

from tcbot.modules.help import (
    HELP_CONTENT,
    HELP_TOPICS_CMD,
    HELP_TOPICS_MENU,
)

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")


# ────────────────────── HELP_CONTENT structure ──────────────────── #


def test_help_content_is_non_empty() -> None:
    """At least one module must expose help content."""
    assert HELP_CONTENT, "HELP_CONTENT is empty - no modules loaded"


def test_help_content_keys_prefixed_with_help() -> None:
    """All keys must follow the 'help_<module>' naming convention."""
    for key in HELP_CONTENT:
        assert key.startswith("help_"), f"Key {key!r} does not start with 'help_'"


def test_help_content_values_are_triples() -> None:
    """Each value must be (display_name, overview_text, sections)."""
    for key, val in HELP_CONTENT.items():
        assert isinstance(val, tuple) and len(val) == 3, (
            f"Entry {key!r} is not a 3-tuple"
        )


def test_help_content_display_names_non_empty() -> None:
    for key, (name, _, _) in HELP_CONTENT.items():
        assert name and name.strip(), f"Empty display name for {key!r}"


def test_help_content_overview_texts_non_empty() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert text and text.strip(), f"Empty overview text for {key!r}"


def test_help_content_sections_are_lists() -> None:
    for key, (_, _, sections) in HELP_CONTENT.items():
        assert isinstance(sections, list), f"Sections for {key!r} are not a list"


def test_help_content_section_entries_are_string_pairs() -> None:
    """Every section entry must be a (heading, body) string pair."""
    for key, (_, _, sections) in HELP_CONTENT.items():
        for i, entry in enumerate(sections):
            assert (
                isinstance(entry, tuple)
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
            ), f"Section {i} of {key!r} is malformed: {entry!r}"


def test_help_content_no_emoji_in_overview_texts() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert not _EMOJI_RE.search(text), f"Emoji in overview of {key!r}: {text!r}"


def test_help_content_no_em_dash_in_overview_texts() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert not _EMDASH_RE.search(text), f"Em-dash in overview of {key!r}: {text!r}"


# ─────────────────── HELP_TOPICS_MENU / CMD ─────────────────────── #


def test_topics_menu_non_empty() -> None:
    assert HELP_TOPICS_MENU, "HELP_TOPICS_MENU is empty"


def test_topics_cmd_non_empty() -> None:
    assert HELP_TOPICS_CMD, "HELP_TOPICS_CMD is empty"


def test_topics_menu_same_length_as_help_content() -> None:
    assert len(HELP_TOPICS_MENU) == len(HELP_CONTENT)


def test_topics_cmd_same_length_as_help_content() -> None:
    assert len(HELP_TOPICS_CMD) == len(HELP_CONTENT)


def test_topics_menu_entries_are_name_key_pairs() -> None:
    for entry in HELP_TOPICS_MENU:
        assert isinstance(entry, tuple) and len(entry) == 2
        name, key = entry
        assert name and key
        assert key.startswith("help_")


def test_topics_cmd_entries_use_helpc_prefix() -> None:
    """Command-path topics must use 'helpc_' callback prefix."""
    for entry in HELP_TOPICS_CMD:
        _, key = entry
        assert key.startswith("helpc_"), f"CMD key {key!r} lacks 'helpc_' prefix"


def test_topics_menu_sorted_by_display_name() -> None:
    """Topics menu must be alphabetically sorted (case-insensitive)."""
    names = [name for name, _ in HELP_TOPICS_MENU]
    assert names == sorted(names, key=str.lower), "HELP_TOPICS_MENU is not sorted"


def test_topics_cmd_display_names_match_menu() -> None:
    """CMD topics must have the same display names as the menu topics."""
    menu_names = {name for name, _ in HELP_TOPICS_MENU}
    cmd_names = {name for name, _ in HELP_TOPICS_CMD}
    assert menu_names == cmd_names


def test_topics_cmd_keys_derived_from_menu_keys() -> None:
    """helpc_<slug> must match a corresponding help_<slug> entry."""
    menu_keys = {key for _, key in HELP_TOPICS_MENU}
    for _, cmd_key in HELP_TOPICS_CMD:
        slug = cmd_key[6:]  # strip "helpc_"
        assert f"help_{slug}" in menu_keys, (
            f"CMD key {cmd_key!r} has no matching menu entry"
        )
