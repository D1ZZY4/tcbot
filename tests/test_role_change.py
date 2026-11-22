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
from tcbot.modules import admins
from tcbot.modules.helper.buttons import role_change_btn
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.pipelines import roles_flow
from tcbot.modules.helper.pipelines.promote_flow import Promote
from tcbot.modules.helper.pipelines.roles_flow import (
    change_role_for_staff,
    is_role_change_request,
)


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
    monkeypatch.setattr(roles_flow, "banned_target_refusal", _no_ban)
    monkeypatch.setattr(roles_flow, "send_log", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(roles_flow, "locale_for_user", _locale)
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


def test_promote_on_roled_target_is_recognised_as_a_change() -> None:
    """The reported case: /tcpromote @admin moderator routes to a change.

    The old /tcpromote path refused any Admin target with an identity
    refusal before the change workflow could run, so the role never changed.
    The decision helper now separates role changes from fresh promotions.
    """
    assert is_role_change_request("admin", "moderator", "owner") is True
    assert is_role_change_request("moderator", "developer", "admin") is True
    assert is_role_change_request("admin", "admin", "owner") is True
    # * No role given on a roled target -> show the change picker.
    assert is_role_change_request("moderator", None, "owner") is True
    # * A user with no role is a fresh promotion, not a change.
    assert is_role_change_request(None, "moderator", "owner") is False
    # * Admin may not grant the Admin tier; that stays a queued request.
    assert is_role_change_request("moderator", "admin", "admin") is False


def test_promote_command_routes_an_admin_target_to_the_change_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact reported path: /tcpromote @user moderator on an Admin.

    The command must call the role-change workflow rather than emit the old
    "already an Admin" identity refusal. The wrappers are peeled so the
    routing decision can be exercised without the decorators.
    """
    changed: list[tuple[int, str]] = []
    replies: list[str] = []

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _origin(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def _resolve(*_args: Any, **_kwargs: Any) -> tuple[str, int, str]:
        return "owner", 42, "Zexshia"

    async def _classify(*_args: Any, **_kwargs: Any) -> tuple[Identity, str]:
        return Identity("admin", 42, "Zexshia"), "admin"

    async def _change(
        _bot: Any,
        _admin_id: int,
        _admin_fname: str,
        target_id: int,
        _target_fname: str,
        role: str,
        _locale: str | None,
    ) -> tuple[bool, str]:
        changed.append((target_id, role))
        return True, "changed"

    async def _reply(_msg: Any, text: str, **_kwargs: Any) -> None:
        replies.append(text)

    monkeypatch.setattr(admins, "locale_for_update", _locale)
    monkeypatch.setattr(admins, "require_federation_origin", _origin)
    monkeypatch.setattr(admins, "resolve_executor_target", _resolve)
    monkeypatch.setattr(admins, "classify_and_load_role", _classify)
    monkeypatch.setattr(roles_flow, "change_role_for_staff", _change)
    monkeypatch.setattr(admins, "reply_rich", _reply)

    msg = SimpleNamespace(
        text="/tcpromote @Zexshia moderator",
        chat=SimpleNamespace(id=-100999, type="supergroup"),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1, first_name="Owner"),
        effective_message=msg,
        effective_chat=msg.chat,
    )
    body: Any = admins.cmd_promote
    while hasattr(body, "__wrapped__"):
        body = body.__wrapped__
    asyncio.run(body(update, SimpleNamespace(bot=object())))

    assert changed == [(42, "moderator")]
    assert replies == ["changed"]


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
