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
from tcbot.modules.helper.pipelines import (
    promote_request,
    promote_steps,
    transfer_owner,
)

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
    executor_role: str = "owner",
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

    async def _remove_role(user_id: int, **kwargs: Any) -> bool:
        _ = (user_id, kwargs)
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

    async def _effective_role(user_id: int, *, fresh: bool = False) -> str | None:
        _ = fresh
        return executor_role if user_id == 1 else current_role

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)
    monkeypatch.setattr(db.users_roles, "set_role", _set_role)
    monkeypatch.setattr(db.users_roles, "remove_role", _remove_role)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _effective_role)
    monkeypatch.setattr(db.users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.queues_db, "enqueue", _enqueue)
    monkeypatch.setattr(promote_request, "locale_for_user", _locale)
    _ = current_role
    return seen


def test_available_roles_follow_the_executor_rank() -> None:
    """The Owner assigns every role; an Admin only the sub-roles."""
    assert promote_steps.Promote.available_roles_for("owner") == [
        "admin",
        "developer",
        "moderator",
    ]
    assert promote_steps.Promote.available_roles_for("admin") == [
        "developer",
        "moderator",
    ]
    assert promote_steps.Promote.available_roles_for("developer") == []
    assert promote_steps.Promote.available_roles_for("moderator") == []


def test_owner_assigns_admin_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Owner promotion of Admin writes the admin record."""
    seen = _install_promote(monkeypatch)
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(), 1, "Owner", 42, "Target", "admin", "en-US"
        )
    )
    assert ok is True
    assert seen["added"] == [(42, 1)]
    assert seen["enqueued"] == []


def test_admin_promotion_to_admin_queues_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Admin may not grant Admin; the request goes to the Owner."""
    seen = _install_promote(monkeypatch, executor_role="admin")
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(), 1, "Admin", 42, "Target", "admin", "en-US"
        )
    )
    assert ok is True
    assert seen["added"] == []
    assert seen["enqueued"] == [42]


def test_admin_assigns_a_subrole_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Admin may grant Developer and Moderator directly."""
    seen = _install_promote(monkeypatch, executor_role="admin")
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Admin",
            42,
            "Target",
            "developer",
            "en-US",
        )
    )
    assert ok is True
    assert seen["roles"] == [(42, "developer")]


def test_developer_may_not_assign_any_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Developer has no assignment rights."""
    seen = _install_promote(monkeypatch, executor_role="developer")
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Developer",
            42,
            "Target",
            "moderator",
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
    seen = _install_promote(monkeypatch, current_role="admin")
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Owner",
            42,
            "Target",
            "developer",
            "en-US",
        )
    )
    assert ok is False
    assert seen["roles"] == []


def test_promotion_refuses_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Owner role is never assignable through a promotion."""
    seen = _install_promote(monkeypatch, current_role="owner")
    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Owner",
            42,
            "Target",
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
    owner_still_current: bool = True,
) -> dict[str, Any]:
    """Install the collaborators of the ownership-transfer path."""
    seen: dict[str, Any] = {"owner": [], "admins": [], "roles": []}

    async def _transfer(previous_owner: int, new_owner: int) -> None:
        if add_admin_fails:
            raise RuntimeError("write failed")
        seen["owner"].append(new_owner)
        seen["admins"].append(previous_owner)

    async def _is_owner(user_id: int, *, fresh: bool = False) -> bool:
        _ = (user_id, fresh)
        return owner_still_current

    async def _remove_role(user_id: int, **kwargs: Any) -> bool:
        _ = kwargs
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

    async def _locale(user_id: int) -> str:
        _ = user_id
        return "en-US"

    async def _extract(*args: Any, **kwargs: Any) -> tuple[int, str]:
        _ = (args, kwargs)
        return 42, "Target"

    monkeypatch.setattr(transfer_owner, "extract_target", _extract)
    monkeypatch.setattr(db.users_roles, "transfer_ownership", _transfer)
    monkeypatch.setattr(db.users_roles, "is_owner", _is_owner)
    monkeypatch.setattr(db.users_roles, "remove_role", _remove_role)

    async def _safe_reply(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    monkeypatch.setattr(transfer_owner, "reply_rich", _safe_reply)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(transfer_owner.identity, "classify", _classify)
    monkeypatch.setattr(transfer_owner.identity, "verify_not_bot", _verify)
    monkeypatch.setattr(transfer_owner.error_reporter, "set_owner", lambda uid: None)
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
        effective_user=SimpleNamespace(id=1, first_name="Owner"),
        effective_message=_FakeMessage(),
    )


def test_transfer_grants_ownership_and_keeps_the_old_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful transfer replaces the owner and keeps the previous one."""
    seen = _install_transfer(monkeypatch)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == [42]
    assert seen["admins"] == [1]
    # * Clearing the target's old role belongs to the atomic transfer, not a
    # * separate pre-write. A successful transfer therefore records no
    # * standalone remove_role call.
    assert seen["roles"] == []


def test_transfer_refuses_a_banned_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A banned user must never gain owner powers."""
    seen = _install_transfer(monkeypatch, banned=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []
    assert seen["admins"] == []
    assert seen["roles"] == []


def test_transfer_refuses_when_the_owner_changed_mid_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent transfer must not be overwritten by a stale command."""
    seen = _install_transfer(monkeypatch, owner_still_current=False)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []
    assert seen["admins"] == []
    assert seen["roles"] == []


def test_transfer_refuses_a_bot_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bot owner would brick the federation leadership."""
    seen = _install_transfer(monkeypatch, bot_target=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []


def test_a_failed_transfer_keeps_the_current_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The swap and the previous Owner's grant are one atomic decision."""
    seen = _install_transfer(monkeypatch, add_admin_fails=True)
    ctx = SimpleNamespace(bot=_bot())
    asyncio.run(
        transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
    )
    assert seen["owner"] == []
    assert seen["admins"] == []
    # * A failed swap must leave the target's existing role untouched.
    assert seen["roles"] == []
