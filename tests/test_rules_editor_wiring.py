# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Every button the rules editor emits has a reachable handler."""

from __future__ import annotations

import re

from telegram.ext import CallbackQueryHandler, ConversationHandler

from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.pipelines.rules_flow import (
    WAITING_CONFIRM_DISCARD,
    WAITING_EDITOR_MENU,
    build_rules_conv,
)


def _patterns(conv: ConversationHandler, state: int) -> list[re.Pattern[str]]:
    return [
        handler.pattern
        for handler in conv.states[state]
        if isinstance(handler, CallbackQueryHandler)
        and isinstance(handler.pattern, re.Pattern)
    ]


def _emitted() -> set[str]:
    category = {"category_key": "example", "title": "Example"}
    item = {"id": 1, "title": "Item"}
    callbacks: set[str] = set()
    for markup in (
        rules_btn.editor_panel_btn(),
        rules_btn.categories_btn([category]),
        rules_btn.items_btn([item]),
        rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no"),
    ):
        for row in markup.inline_keyboard:
            for button in row:
                if isinstance(button.callback_data, str):
                    callbacks.add(button.callback_data)
    return callbacks


def test_editor_and_confirmation_callbacks_are_wired() -> None:
    conv = build_rules_conv()
    menu = _patterns(conv, WAITING_EDITOR_MENU)
    confirm = _patterns(conv, WAITING_CONFIRM_DISCARD)

    unverified = [
        callback
        for callback in sorted(_emitted())
        if not any(p.fullmatch(callback) for p in [*menu, *confirm])
    ]

    assert unverified == []


def test_the_editor_enters_through_the_tcrules_command() -> None:
    conv = build_rules_conv()
    entry_patterns = [
        handler.pattern
        for handler in conv.entry_points
        if isinstance(handler, CallbackQueryHandler)
    ]
    assert entry_patterns == []
    assert conv.entry_points
