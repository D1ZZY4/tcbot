# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Existing staff members can move between assignable roles, including down."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot import database as db
from tcbot.modules.helper.buttons import role_change_btn
from tcbot.modules.helper.pipelines import promote_flow
from tcbot.modules.helper.pipelines.promote_flow import Promote, change_role_for_staff


class _Bot:
    """Minimal bot double; only direct DMs are used on this path."""

    async def send_message(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(message_id=1)


async def _no_ban(*_args: Any, **_kwargs: Any) -> None:
    return None


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    executor: str | None,
    target: str | None,
) -> list[tuple[int, str, int]]:
    """Stub fresh role reads and capture the role mutation."""
    calls: list[tuple[int, str, int]] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return executor if user_id == 1 else target

    async def _change(user_id: int, role: str, assigned_by: int) -> None:
        calls.append((user_id, role, assigned_by))

    async def _locale(_uid: int) -> str:
        return "en-US"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_roles, "change_role", _change)
    monkeypatch.setattr(promote_flow, "banned_target_refusal", _no_ban)
    monkeypatch.setattr(promote_flow, "send_log", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(promote_flow, "locale_for_user", _locale)
    return calls


def test_admin_can_move_to_moderator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported case: an Admin becomes a Moderator without a demote."""
    calls = _wire(monkeypatch, executor="owner", target="admin")
    ok, text = asyncio.run(
        change_role_for_staff(
            cast("Any", _Bot()), 1, "Owner", 42, "Ada", "moderator", "en-US"
        )
    )
    assert ok is True
    assert calls == [(42, "moderator", 1)]
    assert "Moderator" in text


def test_admin_executor_can_move_developer_to_moderator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(monkeypatch, executor="admin", target="developer")
    ok, _ = asyncio.run(
        change_role_for_staff(
            cast("Any", _Bot()), 1, "Admin", 42, "Ada", "moderator", "en-US"
        )
    )
    assert ok is True
    assert calls == [(42, "moderator", 1)]


def test_owner_target_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _wire(monkeypatch, executor="owner", target="owner")
    ok, _ = asyncio.run(
        change_role_for_staff(
            cast("Any", _Bot()), 1, "Owner", 42, "Ada", "moderator", "en-US"
        )
    )
    assert ok is False
    assert calls == []


def test_same_role_and_unassignable_role_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(monkeypatch, executor="owner", target="admin")
    ok, _ = asyncio.run(
        change_role_for_staff(
            cast("Any", _Bot()), 1, "Owner", 42, "Ada", "admin", "en-US"
        )
    )
    assert ok is False
    assert calls == []
    assert Promote.available_roles_for("developer") == []


def test_role_change_button_excludes_current_role() -> None:
    markup = role_change_btn(
        42, ["admin", "developer", "moderator"], "admin", "en-US", 1
    )
    callbacks = {
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "role_change:developer:42:1" in callbacks
    assert "role_change:moderator:42:1" in callbacks
    assert "role_change:admin:42:1" not in callbacks
    assert "role_change_cancel:42:1" in callbacks
