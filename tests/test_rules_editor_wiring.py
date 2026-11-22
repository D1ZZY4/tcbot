# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Every button the rules editor emits has a reachable handler."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telegram.ext import CallbackQueryHandler, ConversationHandler

from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.pipelines import rules_flow
from tcbot.modules.helper.pipelines.rules_flow import (
    WAITING_CONFIRM_DISCARD,
    WAITING_EDITOR_MENU,
    build_rules_conv,
)

# * These two exits are owned by start.py's global handlers, so they work
# * even when a conversation state has no matching pattern.
_GLOBAL_EXITS = {"back_to_start", "close_msg"}


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
        for callback in sorted(_emitted() - _GLOBAL_EXITS)
        if not any(p.fullmatch(callback) for p in [*menu, *confirm])
    ]

    assert unverified == []


def test_every_rules_menu_offers_back_and_close() -> None:
    category = {"category_key": "example", "title": "Example"}
    menus = (
        rules_btn.editor_panel_btn(),
        rules_btn.categories_btn([category]),
        rules_btn.items_btn([{"id": 1, "title": "Item"}]),
        rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no"),
        rules_btn.prompt_btn("rules_panel"),
        rules_btn.rules_menu_btn([category]),
        rules_btn.category_back_btn(),
    )
    for markup in menus:
        callbacks = {
            b.callback_data
            for row in markup.inline_keyboard
            for b in row
            if isinstance(b.callback_data, str)
        }
        assert "close_msg" in callbacks
        assert "back_to_start" in callbacks or any(
            cb.startswith("rules_") for cb in callbacks
        )


def test_rename_prompt_edits_the_invoking_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tapping Rename replaces the category panel, it does not reply anew."""
    edits: list[dict[str, Any]] = []
    replies: list[Any] = []

    async def _allowed(_update: Any) -> bool:
        return True

    async def _draft(_update: Any, _ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {"id": 1}, {"id": 2}

    async def _answer() -> None:
        return None

    async def _edit(_q: Any, _text: str, **kwargs: Any) -> None:
        edits.append(kwargs)

    async def _reply(*_args: Any, **_kwargs: Any) -> None:
        replies.append(_args)

    monkeypatch.setattr(rules_flow, "editor_allowed", _allowed)
    monkeypatch.setattr(rules_flow.rules_editor, "_set_and_draft", _draft)
    monkeypatch.setattr(rules_flow, "safe_edit_cb", _edit)
    monkeypatch.setattr(rules_flow, "reply_rich", _reply)
    monkeypatch.setattr(rules_flow, "flow_scope", lambda _ctx, _update: {})

    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_cat_rename:conduct", answer=_answer, message=SimpleNamespace()
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
    )
    asyncio.run(
        rules_flow.rules_editor.cat_action(cast("Any", update), cast("Any", None))
    )

    assert len(edits) == 1
    assert replies == []
    markup = edits[0]["reply_markup"]
    callbacks = {
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "close_msg" in callbacks
    assert "rules_categories" in callbacks


def test_the_editor_enters_through_the_tcrules_command() -> None:
    conv = build_rules_conv()
    entry_patterns = [
        handler.pattern
        for handler in conv.entry_points
        if isinstance(handler, CallbackQueryHandler)
    ]
    assert entry_patterns == []
    assert conv.entry_points
