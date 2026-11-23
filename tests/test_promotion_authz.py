# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion authorization: banned targets and executor rank gates."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper import guards
from tcbot.modules.helper.pipelines import promote_steps

# ─────────────────────────── Promotion guards ─────────────────────────── #


def _install_ban(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ban: Any = None,
    raises: BaseException | None = None,
) -> None:
    """Install a fake active-ban lookup."""

    async def _get_active_ban(user_id: int) -> Any:
        _ = user_id
        if raises is not None:
            raise raises
        return ban

    monkeypatch.setattr(db.bans_db, "get_active_ban", _get_active_ban)


def _install_executor_role(monkeypatch: pytest.MonkeyPatch, role: str | None) -> None:
    """Install the fresh role reads at the mutation point.

    The executor is user 1; the target (user 42) starts with no role unless
    a test says otherwise.
    """

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        _ = fresh
        return role if user_id == 1 else None

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)


def test_banned_target_refusal_blocks_a_banned_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active ban must produce a refusal line."""
    _install_ban(monkeypatch, ban={"_id": "b1"})
    refusal = asyncio.run(
        guards.banned_target_refusal(42, "en-US", log_label="test ban-guard")
    )
    assert refusal is not None
    assert "Banned" in refusal


def test_banned_target_refusal_allows_a_clean_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active ban means no refusal."""
    _install_ban(monkeypatch, ban=None)
    assert (
        asyncio.run(
            guards.banned_target_refusal(42, "en-US", log_label="test ban-guard")
        )
        is None
    )


def test_banned_target_refusal_fails_closed_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown ban state must refuse, not grant rank."""
    _install_ban(monkeypatch, raises=RuntimeError("db down"))
    refusal = asyncio.run(
        guards.banned_target_refusal(42, "en-US", log_label="test ban-guard")
    )
    assert refusal is not None


def test_banned_target_refusal_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must never be turned into a refusal line."""
    _install_ban(monkeypatch, raises=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            guards.banned_target_refusal(42, "en-US", log_label="test ban-guard")
        )


def test_promote_execute_refuses_a_banned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The promotion chokepoint must not grant rank to a banned user."""
    _install_ban(monkeypatch, ban={"_id": "b1"})
    _install_executor_role(monkeypatch, "owner")

    granted: list[int] = []

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        granted.append(user_id)

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)

    ok, text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Owner",
            42,
            "Target",
            "admin",
            "en-US",
        )
    )
    assert ok is False
    assert granted == []
    assert "Banned" in text


def test_promote_execute_rechecks_the_executor_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demotion during target classification must not still grant rank.

    The command checks the executor at entry, then classifies the target
    and probes the bot before the grant. The grant re-reads the role, so
    the demoted executor cannot assign the tier it no longer holds.
    """
    _install_ban(monkeypatch, ban=None)
    _install_executor_role(monkeypatch, "moderator")
    granted: list[int] = []

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        granted.append(user_id)

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)

    ok, text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(),
            1,
            "Owner",
            42,
            "Target",
            "admin",
            "en-US",
        )
    )
    assert ok is False
    assert granted == []
    assert text


def test_promote_execute_fails_closed_on_a_role_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown executor role refuses the grant instead of allowing it."""

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        _ = (user_id, fresh)
        raise RuntimeError("role table unavailable")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    granted: list[int] = []

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        granted.append(user_id)

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)

    ok, _text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(), 1, "Owner", 42, "Target", "admin", "en-US"
        )
    )
    assert ok is False
    assert granted == []


def test_promote_execute_allows_a_clean_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean target still reaches the assignment path."""
    _install_ban(monkeypatch, ban=None)
    _install_executor_role(monkeypatch, "owner")
    assigned: list[tuple[int, str]] = []

    async def _set_role(user_id: int, role: str, assigned_by: int) -> None:
        _ = assigned_by
        assigned.append((user_id, role))

    monkeypatch.setattr(db.users_roles, "set_role", _set_role)
    monkeypatch.setattr(db.users_cache, "upsert_user", _noop_user_upsert)

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
    assert ok is True
    assert assigned == [(42, "developer")]


def test_promote_execute_rechecks_the_target_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target promoted while the prompt was open is not overwritten.

    The command and the role picker read the target role before the grant.
    A Owner promoting the target to Admin in that window must not be
    undone by an older Developer grant decided against the stale role.
    """
    _install_ban(monkeypatch, ban=None)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        _ = fresh
        return "owner" if user_id == 1 else "admin"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assigned: list[tuple[int, str]] = []

    async def _set_role(user_id: int, role: str, assigned_by: int) -> None:
        _ = assigned_by
        assigned.append((user_id, role))

    monkeypatch.setattr(db.users_roles, "set_role", _set_role)
    monkeypatch.setattr(db.users_cache, "upsert_user", _noop_user_upsert)

    ok, text = asyncio.run(
        promote_steps.Promote.execute(
            _bot(), 1, "Owner", 42, "Target", "developer", "en-US"
        )
    )

    assert ok is False
    assert assigned == []
    assert "Admin" in text


def test_promote_request_refuses_a_banned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A banned user must not reach the Owner's approval card."""
    _install_ban(monkeypatch, ban={"_id": "b1"})
    enqueued: list[int] = []

    async def _enqueue(target_id: int, *args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        enqueued.append(target_id)
        return "req-1"

    monkeypatch.setattr(db.queues_db, "enqueue", _enqueue)

    ok, _text = asyncio.run(
        promote_steps.request_admin(_bot(), 1, 42, "Target", locale="en-US")
    )
    assert ok is False
    assert enqueued == []


# ───────────────────────────── Sync rank gate ─────────────────────────── #


# ──────────────────────────────── Helpers ─────────────────────────────── #


def _bot() -> Any:
    """Return a bot double that swallows every send."""

    class _Bot:
        id = 999

        async def send_message(self, *args: Any, **kwargs: Any) -> Any:
            _ = (args, kwargs)
            return None

    return _Bot()


async def _noop_user_upsert(*args: Any, **kwargs: Any) -> None:
    """Stand-in for the member-cache upsert."""
    _ = (args, kwargs)
