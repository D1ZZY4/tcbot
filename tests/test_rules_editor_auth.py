# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Editor capability checks must gate every rules mutation surface."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import rules_editor, rules_editor_draft


def test_editor_allowed_reads_the_capability_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup failure closes the gate, and a granted capability opens it."""
    allowed = asyncio.Event()

    async def _has_permission(uid: int, key: str) -> bool:
        assert key == "rules.manage"
        return allowed.is_set()

    monkeypatch.setattr(db.users_roles, "has_permission", _has_permission)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))

    assert asyncio.run(rules_editor.editor_allowed(cast("Any", update))) is False
    allowed.set()
    assert asyncio.run(rules_editor.editor_allowed(cast("Any", update))) is True


def test_category_action_refuses_a_revoked_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale category button cannot mutate rules after revocation."""
    moved: list[Any] = []

    async def _no_permission(update: Any) -> bool:
        return False

    async def _move(*args: Any) -> None:
        moved.append(args)

    async def _answer() -> None:
        return None

    monkeypatch.setattr(rules_editor_draft, "editor_allowed", _no_permission)
    monkeypatch.setattr(rules_editor_draft, "refuse_editor", _no_permission)
    monkeypatch.setattr(db.rules_db, "move_category", _move)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_cat_del:spam", answer=_answer, message=None
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
    )

    asyncio.run(
        rules_editor_draft.rules_draft_editor.cat_action(
            cast("Any", update), cast("Any", SimpleNamespace())
        )
    )

    assert moved == []


def test_typed_item_writes_to_the_fresh_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale Add-item step must never append to a published version."""
    calls: list[tuple[Any, ...]] = []
    scope: dict[str, Any] = {
        "rules_version": {"id": 12, "status": "published"},
        "rules_step": "item_url",
        "rules_item_title": "No spam",
        "rules_item_body": "Be kind",
        "rules_category": {"category_key": "general"},
    }

    async def _draft(ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {"id": 3}, {"id": 99, "status": "draft"}

    async def _add_item(*args: Any) -> None:
        calls.append(args)

    async def _items(ctx: Any) -> int:
        return 0

    monkeypatch.setattr(rules_editor_draft, "set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "add_item", _add_item)
    monkeypatch.setattr(rules_editor_draft.rules_draft_editor, "items", _items)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="https://example.com/rule"),
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=7, type=SimpleNamespace(value="private")),
        user_data=scope,
    )
    asyncio.run(rules_editor_draft.rules_draft_editor.on_text(cast("Any", update)))

    assert calls and calls[0][0] == 99


def test_typed_dash_skips_the_reference_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented '-' sentinel stores no URL instead of being rejected."""
    calls: list[tuple[Any, ...]] = []
    scope: dict[str, Any] = {
        "rules_version": {"id": 12, "status": "draft"},
        "rules_step": "item_url",
        "rules_item_title": "No spam",
        "rules_item_body": "Be kind",
        "rules_category": {"category_key": "general"},
    }

    async def _draft(ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {"id": 3}, {"id": 12, "status": "draft"}

    async def _add_item(*args: Any) -> None:
        calls.append(args)

    async def _items(ctx: Any) -> int:
        return 0

    async def _reply(*args: Any, **kwargs: Any) -> None:
        return None

    async def _locale(ctx: Any) -> str:
        return "en-US"

    monkeypatch.setattr(rules_editor_draft, "set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "add_item", _add_item)
    monkeypatch.setattr(rules_editor_draft.rules_draft_editor, "items", _items)
    monkeypatch.setattr(rules_editor_draft, "reply_rich", _reply)
    monkeypatch.setattr(rules_editor_draft.rules_draft_editor, "_locale", _locale)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="-"),
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=7, type=SimpleNamespace(value="private")),
        user_data=scope,
    )
    asyncio.run(rules_editor_draft.rules_draft_editor.on_text(cast("Any", update)))

    assert calls and calls[0][4] is None


def test_add_item_from_root_picks_a_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Add Item without a selected category must not discard typed input."""
    scope: dict[str, Any] = {}

    async def _answer() -> None:
        return None

    async def _draft(ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {"id": 3}, {"id": 12, "status": "draft"}

    async def _categories(set_id: int) -> list[dict[str, Any]]:
        return [{"id": 1, "category_key": "general"}]

    async def _locale(ctx: Any) -> str:
        return "en-US"

    async def _edit(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(rules_editor_draft, "set_and_draft", _draft)
    monkeypatch.setattr(db.rules_db, "list_categories", _categories)
    monkeypatch.setattr(rules_editor_draft, "edit_or_reply", _edit)
    monkeypatch.setattr(rules_editor_draft.rules_draft_editor, "_locale", _locale)

    ctx = SimpleNamespace(
        callback_query=SimpleNamespace(answer=_answer),
        effective_message=None,
        user_data=scope,
    )
    asyncio.run(rules_editor_draft.rules_draft_editor.ask_item_title(cast("Any", ctx)))

    assert scope["rules_category"]["category_key"] == "general"
    assert scope["rules_step"] == "item_title"
