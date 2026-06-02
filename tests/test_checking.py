# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.checking - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.checking as checking

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_checking() -> None:
    assert checking.__module_name__ == "Checking"


def test_help_text_is_non_empty() -> None:
    assert isinstance(checking.__help_text__, str)
    assert checking.__help_text__.strip()


def test_help_text_mentions_checkme() -> None:
    assert "checkme" in checking.__help_text__


def test_help_text_mentions_check() -> None:
    assert "check" in checking.__help_text__.lower()


def test_help_sections_is_list_of_tuples() -> None:
    sections = checking.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in checking.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_checkme() -> None:
    lookup = dict(checking.__help_sections__)
    assert "checkme" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_check_alias() -> None:
    lookup = dict(checking.__help_sections__)
    assert "/c" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_cme_alias() -> None:
    lookup = dict(checking.__help_sections__)
    assert "cme" in lookup["Commands & Aliases"]


def test_help_sections_no_emdash() -> None:
    for _key, value in checking.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert len(keys) == len(set(keys))


def test_help_sections_has_checkme_section() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "/checkme" in keys


def test_help_sections_has_check_section() -> None:
    keys = [k for k, _ in checking.__help_sections__]
    assert "/check" in keys


def test_help_sections_checkme_mentions_appeal() -> None:
    lookup = dict(checking.__help_sections__)
    assert "appeal" in lookup["/checkme"].lower()


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(checking.__handlers__, list)
    assert len(checking.__handlers__) >= 2


def test_handlers_include_message_and_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler, MessageHandler

    handler_types = {type(h) for h in checking.__handlers__}
    assert MessageHandler in handler_types
    assert CallbackQueryHandler in handler_types


def test_handlers_have_two_message_handlers() -> None:
    from telegram.ext import MessageHandler

    msg_handlers = [h for h in checking.__handlers__ if isinstance(h, MessageHandler)]
    assert len(msg_handlers) == 2


def test_handlers_have_multiple_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler

    cb_handlers = [
        h for h in checking.__handlers__ if isinstance(h, CallbackQueryHandler)
    ]
    assert len(cb_handlers) >= 5
