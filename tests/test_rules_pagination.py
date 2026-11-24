# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The public rules menu is a paged topic index with per-category sections."""

from __future__ import annotations

import re
from typing import Any

from telegram.ext import CallbackQueryHandler

from tcbot.modules import rules as rules_module
from tcbot.modules.helper.buttons import rules as rules_btn

_ITEMS: list[dict[str, Any]] = [
    {
        "category_key": "cheat",
        "category_title": "cheat",
        "title": "Cheat: Istilah",
        "body": "Exploit tools.",
        "sort_order": 1,
        "id": 1,
    },
    {
        "category_key": "cheat",
        "category_title": "cheat",
        "title": "Cheat: Aturan",
        "body": "No cheating.",
        "sort_order": 2,
        "id": 2,
    },
    {
        "category_key": "cheat",
        "category_title": "cheat",
        "title": "Cheat: Sanksi",
        "body": "Federation ban.",
        "sort_order": 3,
        "id": 3,
    },
]


def test_section_names_come_from_stored_item_titles() -> None:
    assert rules_module._category_sections(_ITEMS) == ["Istilah", "Aturan", "Sanksi"]


def test_index_buttons_are_two_per_row_with_paging() -> None:
    categories = [{"category_key": f"c{i}", "title": f"c{i}"} for i in range(10)]
    markup = rules_btn.rules_index_btn(categories, "en-US")
    rows = markup.inline_keyboard
    assert len(rows[0]) == 2
    callbacks = {b.callback_data for row in rows for b in row}
    assert "rules_show:c0" in callbacks
    assert "rules_index:1" in callbacks
    assert "close_msg" in callbacks


def test_section_buttons_are_two_per_row() -> None:
    markup = rules_btn.category_sections_btn(["Istilah", "Aturan", "Sanksi"], "en-US")
    rows = markup.inline_keyboard
    assert len(rows[0]) == 2
    callbacks = {b.callback_data for row in rows for b in row}
    assert callbacks == {
        "rules_section:0",
        "rules_section:1",
        "rules_section:2",
        "rules_index:0",
        "close_msg",
    }


def test_section_page_offers_only_back_and_close() -> None:
    """A section view is a reading page, not a second list of sections."""
    markup = rules_btn.rules_section_btn("cheat", "en-US")
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert callbacks == {"rules_show:cheat", "close_msg"}


def test_page_index_parses_only_numeric_payloads() -> None:
    assert rules_module._page_from_data("rules_index:7") == 7
    assert rules_module._page_from_data("rules_section:1") == 1
    assert rules_module._page_from_data("rules_next:x") == 0
    assert rules_module._page_from_data(None) == 0


def test_index_and_section_callbacks_are_registered() -> None:
    patterns = [
        handler.pattern
        for handler in rules_module.__handlers__
        if isinstance(handler, CallbackQueryHandler)
        and isinstance(handler.pattern, re.Pattern)
    ]
    assert any(p.pattern == r"^rules_index:\d+$" for p in patterns)
    assert any(p.pattern == r"^rules_section:\d+$" for p in patterns)
