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
from tcbot.modules import rules
from tcbot.modules.helper.pipelines import rules_flow


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

    assert asyncio.run(rules_flow.editor_allowed(cast("Any", update))) is False
    allowed.set()
    assert asyncio.run(rules_flow.editor_allowed(cast("Any", update))) is True


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

    monkeypatch.setattr(rules, "editor_allowed", _no_permission)
    monkeypatch.setattr(rules, "refuse_editor", _no_permission)
    monkeypatch.setattr(db.rules_db, "move_category", _move)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="rules_cat_del:spam", answer=_answer, message=None
        ),
        effective_user=SimpleNamespace(id=7),
        effective_message=None,
    )

    asyncio.run(
        rules.on_rules_cat_action(cast("Any", update), cast("Any", SimpleNamespace()))
    )

    assert moved == []
