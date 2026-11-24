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
from pyrogram.handlers import CallbackQueryHandler as _CallbackQueryHandler
from pyrogram.handlers import MessageHandler as _MessageHandler

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.handlers import (
    ConversationHandler,
)
from tcbot.modules.helper.pipelines import (
    rules_editor,
    rules_editor_draft,
    rules_editor_steps,
)
from tcbot.modules.helper.pipelines.rules_editor import (
    WAITING_CONFIRM_DISCARD,
    WAITING_EDITOR_MENU,
    build_rules_conv,
)

# * These two exits are owned by start.py's global handlers, so they work
# * even when a conversation state has no matching pattern.
_GLOBAL_EXITS = {"back_to_start", "close_msg"}


def _patterns(conv: ConversationHandler, state: int) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for handler in conv.states[state]:
        if not isinstance(handler, _CallbackQueryHandler):
            continue
        flt = getattr(handler, "filters", None)
        pattern = getattr(flt, "p", None)
        if isinstance(pattern, re.Pattern):
            patterns.append(pattern)
    return patterns


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


def test_completed_editor_steps_are_forgotten() -> None:
    """A successful add must leave no pending step for the next chat message."""
    scope: dict[str, Any] = {
        "rules_step": "item_url",
        "rules_item_title": "Spam",
        "rules_item_body": "No spam",
        "rules_category": {"category_key": "spam"},
    }
    rules_editor_steps.clear_item_step(scope)
    assert scope == {"rules_category": {"category_key": "spam"}}

    scope.update(
        {
            "rules_step": "category_title",
            "rules_set": {"id": 1},
            "rules_version": {"id": 2},
            "rules_category_key": "spam",
        }
    )
    rules_editor_steps.clear_editor_scope(scope)
    assert scope == {}


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


def test_every_editor_submenu_offers_close_and_back() -> None:
    category = {"category_key": "example", "title": "Example"}
    submenus = (
        rules_btn.categories_btn([category]),
        rules_btn.items_btn([{"id": 1, "title": "Item"}]),
        rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no"),
        rules_btn.prompt_btn("rules_panel"),
        rules_btn.preview_btn(),
    )
    for markup in submenus:
        callbacks = {
            b.callback_data
            for row in markup.inline_keyboard
            for b in row
            if isinstance(b.callback_data, str)
        }
        assert "close_msg" in callbacks
        assert any(cb.startswith("rules_") for cb in callbacks)


def test_public_rules_pages_navigate_with_prev_next_and_close() -> None:
    """The read-only menu is a paged topic view, with no topic buttons or Back."""
    first = rules_btn.rules_page_btn(0, 3, "en-US")
    middle = rules_btn.rules_page_btn(1, 3, "en-US")
    last = rules_btn.rules_page_btn(2, 3, "en-US")

    def _callbacks(markup: Any) -> set[str]:
        return {
            b.callback_data
            for row in markup.inline_keyboard
            for b in row
            if isinstance(b.callback_data, str)
        }

    assert _callbacks(first) == {"rules_next:1", "close_msg"}
    assert _callbacks(middle) == {"rules_prev:0", "rules_next:2", "close_msg"}
    assert _callbacks(last) == {"rules_prev:1", "close_msg"}
    for markup in (first, middle, last):
        callbacks = _callbacks(markup)
        assert "back_to_start" not in callbacks
        assert "rules_menu" not in callbacks
        assert "rules_show:example" not in callbacks


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

    async def _draft(_ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {"id": 1}, {"id": 2}

    async def _answer() -> None:
        return None

    async def _edit(_q: Any, _text: str, **kwargs: Any) -> None:
        edits.append(kwargs)

    async def _reply(*_args: Any, **_kwargs: Any) -> None:
        replies.append(_args)

    async def _edited(_update: Any, _text: str, markup: Any) -> None:
        edits.append({"reply_markup": markup})

    monkeypatch.setattr(rules_editor_draft, "editor_allowed", _allowed)
    monkeypatch.setattr(rules_editor_draft, "set_and_draft", _draft)
    monkeypatch.setattr(rules_editor_draft, "edit_or_reply", _edited)
    monkeypatch.setattr(rules_editor_draft, "reply_rich", _reply)
    monkeypatch.setattr(rules_editor_draft, "flow_scope", lambda _ctx: {})

    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_cat_rename:conduct", answer=_answer, message=SimpleNamespace()
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
        user_data={},
    )
    asyncio.run(rules_editor_draft.rules_draft_editor.cat_action(cast("Any", update)))

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
        getattr(getattr(handler, "filters", None), "p", None)
        for handler in conv.entry_points
        if isinstance(handler, _CallbackQueryHandler)
    ]
    assert entry_patterns == []
    assert conv.entry_points


def test_the_editor_accepts_the_short_alias() -> None:
    """`/tcrls` is the rules editor alias; `/tcr` remains repair's alias."""
    names = {
        type(rules_editor_steps._TCRULES_CMDS.base).__name__,
        type(rules_editor_steps._TCRULES_CMDS.other).__name__,
    }
    assert "PrefixedCommand(tcrls)" in names
    assert "PrefixedCommand(tcr)" not in names


def test_the_open_in_pm_deep_link_starts_the_editor() -> None:
    """Following ?start=tcrules must start the conversation, not just reply."""
    conv = build_rules_conv()

    def _filter_names(flt: Any) -> set[str]:
        names: set[str] = set()
        stack: list[Any] = [flt]
        while stack:
            current = stack.pop()
            if current is None:
                continue
            names.add(type(current).__name__)
            stack.extend(
                getattr(current, part)
                for part in ("base", "other")
                if hasattr(current, part)
            )
        return names

    assert any(
        isinstance(handler, _MessageHandler)
        and "PrefixedCommand(tcrules)" in _filter_names(handler.filters)
        for handler in conv.entry_points
    )


def _callback_update() -> Any:
    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_preview", answer=_noop, message=SimpleNamespace()
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
        user_data={},
    )


async def _noop() -> None:
    return None


def test_preview_stays_in_the_editor_with_back_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edits: list[dict[str, Any]] = []

    async def _draft(_ctx: Any) -> tuple[dict, dict]:
        return {"id": 1}, {"id": 2}

    async def _categories(set_id: int) -> list:
        return [{"category_key": "cheat", "title": "Cheat"}]

    async def _edited(_update: Any, _text: str, markup: Any) -> None:
        edits.append({"reply_markup": markup})

    async def _locale(_update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(rules_editor_draft, "set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "list_categories", _categories)
    monkeypatch.setattr(rules_editor_draft, "edit_or_reply", _edited)
    monkeypatch.setattr(rules_editor_draft.rules_draft_editor, "_locale", _locale)

    update = _callback_update()
    result = asyncio.run(
        rules_editor_draft.rules_draft_editor.preview(cast("Any", update))
    )

    assert result == WAITING_EDITOR_MENU
    callbacks = {
        b.callback_data
        for row in edits[0]["reply_markup"].inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "close_msg" in callbacks
    assert "rules_panel" in callbacks
    assert "rules_preview_cat:cheat" in callbacks


def test_empty_draft_publish_shows_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publishing an empty draft guides the reader instead of calling publish_rules."""
    edits: list[dict[str, Any]] = []
    called: list[Any] = []

    async def _allowed(_update: Any) -> bool:
        return True

    async def _draft(_ctx: Any) -> tuple[dict, dict]:
        return {"id": 1}, {"id": 2, "items": []}

    async def _all_items(version_id: int) -> list:
        return []

    async def _publish(*args: Any, **kwargs: Any) -> None:
        called.append(args)

    async def _edit(_q: Any, text: str, **kwargs: Any) -> None:
        edits.append({"text": text, **kwargs})

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _edited(_update: Any, text: str, _markup: Any) -> None:
        edits.append({"text": text})

    monkeypatch.setattr(rules_editor, "editor_allowed", _allowed)
    monkeypatch.setattr(rules_editor, "set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "all_items", _all_items)
    monkeypatch.setattr(rules_editor, "publish_rules", _publish)
    monkeypatch.setattr(rules_editor, "edit_or_reply", _edited)
    monkeypatch.setattr(rules_editor.rules_editor, "_locale", _locale)

    update = _callback_update()
    result = asyncio.run(rules_editor.rules_editor.publish(cast("Any", update)))

    assert result == WAITING_EDITOR_MENU
    assert called == []
    assert "Nothing to publish" in edits[0]["text"]
