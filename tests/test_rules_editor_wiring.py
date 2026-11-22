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
from telegram.ext import CallbackQueryHandler, ConversationHandler, MessageHandler

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.messages import rules as rules_msg
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
        rules_btn.editor_panel_btn(has_content=True),
        rules_btn.categories_btn([category]),
        rules_btn.items_btn([item]),
        rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no"),
        rules_btn.preview_btn(),
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


def test_every_rules_menu_offers_close_and_submenus_offer_back() -> None:
    category = {"category_key": "example", "title": "Example"}
    submenus = (
        rules_btn.categories_btn([category]),
        rules_btn.items_btn([{"id": 1, "title": "Item"}]),
        rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no"),
        rules_btn.prompt_btn("rules_panel"),
        rules_btn.preview_btn(),
        rules_btn.rules_menu_btn([category]),
        rules_btn.category_back_btn(),
    )
    for markup in submenus:
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


def test_editor_root_has_close_but_no_back() -> None:
    """The editor panel is the root, so it only offers Close."""
    for markup in (
        rules_btn.editor_panel_btn(),
        rules_btn.editor_panel_btn(has_content=True),
    ):
        callbacks = {
            b.callback_data
            for row in markup.inline_keyboard
            for b in row
            if isinstance(b.callback_data, str)
        }
        assert "close_msg" in callbacks
        assert "back_to_start" not in callbacks
        assert "rules_panel" not in callbacks


def test_empty_editor_hides_publish_and_discard() -> None:
    """An empty draft must not offer to publish or discard nothing."""
    callbacks = {
        b.callback_data
        for row in rules_btn.editor_panel_btn().inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "rules_publish" not in callbacks
    assert "rules_discard" not in callbacks


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


def test_the_open_in_pm_deep_link_starts_the_editor() -> None:
    """Following ?start=tcrules must start the conversation, not just reply."""
    conv = build_rules_conv()
    assert any(
        isinstance(handler, MessageHandler) and "tcrules" in repr(handler.filters)
        for handler in conv.entry_points
    )


def _callback_update() -> Any:
    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_preview", answer=_noop, message=SimpleNamespace()
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
    )


async def _noop() -> None:
    return None


def test_preview_stays_in_the_editor_with_back_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edits: list[dict[str, Any]] = []

    async def _items(version_id: int, category_key: str | None = None) -> list:
        return []

    async def _preview(items: list, locale: str | None) -> str:
        return "preview body"

    async def _edit(_q: Any, _text: str, **kwargs: Any) -> None:
        edits.append(kwargs)

    async def _locale(_update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(db.rules_db, "list_items", _items)
    monkeypatch.setattr(rules_msg, "preview", _preview)
    monkeypatch.setattr(rules_flow, "safe_edit_cb", _edit)
    monkeypatch.setattr(rules_flow.rules_editor, "_locale", _locale)
    monkeypatch.setattr(
        rules_flow,
        "flow_scope",
        lambda _ctx, _update: {"rules_version": {"id": 2}},
    )

    update = _callback_update()
    result = asyncio.run(
        rules_flow.rules_editor.preview(cast("Any", update), cast("Any", None))
    )

    assert result == WAITING_EDITOR_MENU
    callbacks = {
        b.callback_data
        for row in edits[0]["reply_markup"].inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "rules_panel" in callbacks
    assert "close_msg" in callbacks


def test_empty_draft_publish_shows_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publishing an empty draft guides the reader instead of calling publish_rules."""
    edits: list[dict[str, Any]] = []
    called: list[Any] = []

    async def _allowed(_update: Any) -> bool:
        return True

    async def _draft(_update: Any, _ctx: Any) -> tuple[dict, dict]:
        return {"id": 1}, {"id": 2, "items": []}

    async def _all_items(version_id: int) -> list:
        return []

    async def _publish(*args: Any, **kwargs: Any) -> None:
        called.append(args)

    async def _edit(_q: Any, text: str, **kwargs: Any) -> None:
        edits.append({"text": text, **kwargs})

    async def _locale(_update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(rules_flow, "editor_allowed", _allowed)
    monkeypatch.setattr(rules_flow.rules_editor, "_set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "all_items", _all_items)
    monkeypatch.setattr(rules_flow, "publish_rules", _publish)
    monkeypatch.setattr(rules_flow, "safe_edit_cb", _edit)
    monkeypatch.setattr(rules_flow.rules_editor, "_locale", _locale)

    update = _callback_update()
    result = asyncio.run(
        rules_flow.rules_editor.publish(cast("Any", update), cast("Any", None))
    )

    assert result == WAITING_EDITOR_MENU
    assert called == []
    assert "Nothing to publish" in edits[0]["text"]
