# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role assignment rules, the queued-request decision, and ownership transfer."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.pipelines import promote_flow, transfer_flow

# ─────────────────────────── Promotion rules ───────────────────────────── #


def _bot() -> Any:
    """Return a bot double that swallows every send."""

    class _Bot:
        id = 999

        async def send_message(self, *args: Any, **kwargs: Any) -> Any:
            _ = (args, kwargs)
            return None

    return _Bot()


def _install_promote(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_role: str | None = None,
    banned: bool = False,
) -> dict[str, Any]:
    """Install the collaborators of the promotion path."""
    seen: dict[str, Any] = {"added": [], "roles": [], "enqueued": []}

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        seen["added"].append((user_id, promoted_by))

    async def _set_role(user_id: int, role: str, assigned_by: int) -> None:
        _ = assigned_by
        seen["roles"].append((user_id, role))

    async def _remove_role(user_id: int) -> bool:
        _ = user_id
        return True

    async def _upsert(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    async def _ban(user_id: int) -> Any:
        _ = user_id
        return {"_id": "b1"} if banned else None

    async def _enqueue(target_id: int, *args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        seen["enqueued"].append(target_id)
        return "req-1"

    async def _owner(*args: Any, **kwargs: Any) -> int:
        _ = (args, kwargs)
        return 1

    async def _locale(user_id: int) -> str:
        _ = user_id
        return "en-US"

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)
    monkeypatch.setattr(db.users_roles, "set_role", _set_role)
    monkeypatch.setattr(db.users_roles, "remove_role", _remove_role)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.queues_db, "enqueue", _enqueue)
    monkeypatch.setattr(promote_flow, "locale_for_user", _locale)
    _ = current_role
    return seen


def test_available_roles_follow_the_executor_rank() -> None:
    """The Founder assigns every role; an Admin only the sub-roles."""
    assert promote_flow.Promote.available_roles_for("founder") == [
        "admin",
        "developer",
        "tester",
    ]
    assert promote_flow.Promote.available_roles_for("admin") == ["developer", "tester"]
    assert promote_flow.Promote.available_roles_for("developer") == []
    assert promote_flow.Promote.available_roles_for("tester") == []


def test_founder_assigns_admin_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Founder promotion of Admin writes the admin record."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(), 1, "Founder", "founder", 42, "Target", None, "admin", "en-US"
        )
    )
    assert ok is True
    assert seen["added"] == [(42, 1)]
    assert seen["enqueued"] == []


def test_admin_promotion_to_admin_queues_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Admin may not grant Admin; the request goes to the Founder."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(), 1, "Admin", "admin", 42, "Target", None, "admin", "en-US"
        )
    )
    assert ok is True
    assert seen["added"] == []
    assert seen["enqueued"] == [42]


def test_admin_assigns_a_subrole_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Admin may grant Developer and Tester directly."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Admin",
            "admin",
            42,
            "Target",
            None,
            "developer",
            "en-US",
        )
    )
    assert ok is True
    assert seen["roles"] == [(42, "developer")]


def test_developer_may_not_assign_any_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Developer has no assignment rights."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Developer",
            "developer",
            42,
            "Target",
            None,
            "tester",
            "en-US",
        )
    )
    assert ok is False
    assert seen["roles"] == []
    assert seen["added"] == []


def test_promotion_refuses_a_higher_ranked_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that already outranks the new role is refused."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Founder",
            "founder",
            42,
            "Target",
            "admin",
            "developer",
            "en-US",
        )
    )
    assert ok is False
    assert seen["roles"] == []


def test_promotion_refuses_the_founder(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Founder role is never assignable through a promotion."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Founder",
            "founder",
            42,
            "Target",
            "founder",
            "developer",
            "en-US",
        )
    )
    assert ok is False
    assert seen["roles"] == []


# ─────────────────────── Ownership transfer rules ──────────────────────── #


def _install_transfer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    banned: bool = False,
    bot_target: bool = False,
    add_admin_fails: bool = False,
) -> dict[str, Any]:
    """Install the collaborators of the ownership-transfer path."""
    seen: dict[str, Any] = {"owner": [], "admins": [], "roles": []}

    async def _set_owner(user_id: int) -> None:
        seen["owner"].append(user_id)

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        _ = promoted_by
        if add_admin_fails:
            raise RuntimeError("write failed")
        seen["admins"].append(user_id)

    async def _remove_role(user_id: int) -> bool:
        seen["roles"].append(user_id)
        return True

    async def _ban(user_id: int) -> Any:
        _ = user_id
        return {"_id": "b1"} if banned else None

    async def _classify(*args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        kind = "other_bot" if bot_target else "user"
        return Identity(kind, 42, "Target", None, is_bot=bot_target)

    async def _verify(*args: Any, **kwargs: Any) -> bool | None:
        _ = (args, kwargs)
        return not bot_target

    async def _upsert(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    async def _resolve_and_check(*args: Any, **kwargs: Any) -> tuple[str, str | None]:
        _ = (args, kwargs)
        return ("founder", None)

    async def _locale(user_id: int) -> str:
        _ = user_id
        return "en-US"

    async def _extract(*args: Any, **kwargs: Any) -> tuple[int, str]:
        _ = (args, kwargs)
        return 42, "Target"

    monkeypatch.setattr(transfer_flow, "extract_target", _extract)
    monkeypatch.setattr(db.users_roles, "set_owner", _set_owner)
    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)
    monkeypatch.setattr(db.users_roles, "remove_role", _remove_role)
    monkeypatch.setattr(transfer_flow, "resolve_and_check", _resolve_and_check)

    async def _safe_reply(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    monkeypatch.setattr(transfer_flow, "safe_reply", _safe_reply)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(transfer_flow.identity, "classify", _classify)
    monkeypatch.setattr(transfer_flow.identity, "verify_not_bot", _verify)
    monkeypatch.setattr(transfer_flow.error_reporter, "set_owner", lambda uid: None)
    return seen


class _FakeMessage:
    """Message double that accepts the transfer replies."""

    def __init__(self) -> None:
        self.text = "/transferowner 42"
        self.chat = SimpleNamespace(id=-100)
        self.replies: list[str] = []

    async def reply_text(self, text: str, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        self.replies.append(text)
        return SimpleNamespace(message_id=1)


def _transfer_update() -> Any:
    """Return an update carrying the current owner and the transfer command."""
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=1, first_name="Founder"),
        effective_message=_FakeMessage(),
    )


def test_transfer_grants_ownership_and_keeps_the_old_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful transfer replaces the owner and keeps the previous one."""
    seen = _install_transfer(monkeypatch)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_flow.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == [42]
    assert seen["admins"] == [1]


def test_transfer_refuses_a_banned_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A banned user must never gain founder powers."""
    seen = _install_transfer(monkeypatch, banned=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_flow.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []
    assert seen["admins"] == []


def test_transfer_refuses_a_bot_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bot owner would brick the federation leadership."""
    seen = _install_transfer(monkeypatch, bot_target=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_flow.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []


def test_transfer_survives_a_failed_previous_owner_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed add_admin never rolls the ownership back."""
    seen = _install_transfer(monkeypatch, add_admin_fails=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_flow.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == [42]
    assert seen["admins"] == []
