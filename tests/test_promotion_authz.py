# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion authorization: banned targets and executor rank gates."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.decorators import checks
from tcbot.modules.helper.pipelines import promote_flow

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


def test_banned_target_refusal_blocks_a_banned_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active ban must produce a refusal line."""
    _install_ban(monkeypatch, ban={"_id": "b1"})
    refusal = asyncio.run(
        checks.banned_target_refusal(42, "en-US", log_label="test ban-guard")
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
            checks.banned_target_refusal(42, "en-US", log_label="test ban-guard")
        )
        is None
    )


def test_banned_target_refusal_fails_closed_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown ban state must refuse, not grant rank."""
    _install_ban(monkeypatch, raises=RuntimeError("db down"))
    refusal = asyncio.run(
        checks.banned_target_refusal(42, "en-US", log_label="test ban-guard")
    )
    assert refusal is not None


def test_banned_target_refusal_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must never be turned into a refusal line."""
    _install_ban(monkeypatch, raises=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            checks.banned_target_refusal(42, "en-US", log_label="test ban-guard")
        )


def test_promote_execute_refuses_a_banned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The promotion chokepoint must not grant rank to a banned user."""
    _install_ban(monkeypatch, ban={"_id": "b1"})

    granted: list[int] = []

    async def _add_admin(user_id: int, promoted_by: int) -> None:
        granted.append(user_id)

    monkeypatch.setattr(db.users_roles, "add_admin", _add_admin)

    ok, text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Founder",
            "founder",
            42,
            "Target",
            None,
            "admin",
            "en-US",
        )
    )
    assert ok is False
    assert granted == []
    assert "Banned" in text


def test_promote_execute_allows_a_clean_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean target still reaches the assignment path."""
    _install_ban(monkeypatch, ban=None)
    assigned: list[tuple[int, str]] = []

    async def _set_role(user_id: int, role: str, assigned_by: int) -> None:
        _ = assigned_by
        assigned.append((user_id, role))

    monkeypatch.setattr(db.users_roles, "set_role", _set_role)
    monkeypatch.setattr(db.users_cache, "upsert_user", _noop_user_upsert)

    ok, _text = asyncio.run(
        promote_flow.Promote.execute(
            _bot(),
            1,
            "Founder",
            "founder",
            42,
            "Target",
            None,
            "developer",
            "en-US",
        )
    )
    assert ok is True
    assert assigned == [(42, "developer")]


def test_promote_request_refuses_a_banned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A banned user must not reach the Founder's approval card."""
    _install_ban(monkeypatch, ban={"_id": "b1"})
    enqueued: list[int] = []

    async def _enqueue(target_id: int, *args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        enqueued.append(target_id)
        return "req-1"

    monkeypatch.setattr(db.queues_db, "enqueue", _enqueue)

    ok, _text = asyncio.run(
        promote_flow.request_admin(_bot(), 1, 42, "Target", locale="en-US")
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
