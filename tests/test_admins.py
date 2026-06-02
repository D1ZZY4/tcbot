# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.admins - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.admins as admins

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_admins() -> None:
    assert admins.__module_name__ == "Admins"


def test_help_text_is_non_empty() -> None:
    assert isinstance(admins.__help_text__, str)
    assert admins.__help_text__.strip()


def test_help_text_mentions_promote() -> None:
    assert "romot" in admins.__help_text__


def test_help_text_mentions_demote() -> None:
    assert "emot" in admins.__help_text__


def test_help_sections_is_list_of_tuples() -> None:
    sections = admins.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in admins.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_contains_role_hierarchy() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert "Role Hierarchy" in keys


def test_help_sections_commands_mentions_tcpromote() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcpromote" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcdemote() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcdemote" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_transferowner() -> None:
    lookup = dict(admins.__help_sections__)
    assert "transferowner" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcpromoterequests() -> None:
    lookup = dict(admins.__help_sections__)
    assert "tcpromoterequests" in lookup["Commands & Aliases"]


def test_help_sections_who_can_use_references_founder() -> None:
    lookup = dict(admins.__help_sections__)
    assert "Founder" in lookup["Who can use"]


def test_help_sections_who_can_use_references_admin() -> None:
    lookup = dict(admins.__help_sections__)
    assert "Admin" in lookup["Who can use"]


def test_help_sections_role_hierarchy_lists_four_ranks() -> None:
    lookup = dict(admins.__help_sections__)
    hierarchy = lookup["Role Hierarchy"]
    for role in ("Founder", "Admin", "Developer", "Tester"):
        assert role in hierarchy, f"Role hierarchy missing: {role}"


def test_help_sections_no_emdash() -> None:
    for _key, value in admins.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in admins.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(admins.__handlers__, list)
    assert len(admins.__handlers__) >= 5


def test_handlers_include_message_and_callback_handlers() -> None:
    from telegram.ext import CallbackQueryHandler, MessageHandler

    handler_types = {type(h) for h in admins.__handlers__}
    assert MessageHandler in handler_types
    assert CallbackQueryHandler in handler_types


def test_handlers_have_five_message_handlers() -> None:
    from telegram.ext import MessageHandler

    msg_handlers = [h for h in admins.__handlers__ if isinstance(h, MessageHandler)]
    assert len(msg_handlers) == 5


def test_handlers_have_callback_handlers_for_promo_and_demote() -> None:
    from telegram.ext import CallbackQueryHandler

    cb_handlers = [
        h for h in admins.__handlers__ if isinstance(h, CallbackQueryHandler)
    ]
    assert len(cb_handlers) >= 3
