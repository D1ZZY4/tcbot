# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The fail-closed unban gate must never let a staff holder keep rank."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import demote_actions

_ARGS: tuple[Any, ...] = (object(), 42, "Target", "moderator", 7, "Admin")


async def _demote(*_args: Any, **_kwargs: Any) -> bool:
    return True


@pytest.mark.parametrize(
    ("demote", "live_role", "expected"),
    [
        (_demote, None, demote_actions.UnbanGate.PROCEED),
    ],
)
@pytest.mark.asyncio
async def test_a_successful_demote_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    demote: Any,
    live_role: str | None,
    expected: demote_actions.UnbanGate,
) -> None:
    """A removed role clears the gate."""
    monkeypatch.setattr(demote_actions.Demote, "execute", demote)

    async def _no_role_read(*_args: Any, **_kwargs: Any) -> str | None:
        raise AssertionError("a successful demote must not re-read the role")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _no_role_read)

    verdict = await demote_actions.demote_before_unban(*_ARGS)
    assert verdict is expected


@pytest.mark.asyncio
async def test_a_failed_demote_blocks_the_unban(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demote that raises fails closed instead of lifting the ban."""

    async def _raises(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("demote failed")

    monkeypatch.setattr(demote_actions.Demote, "execute", _raises)
    verdict = await demote_actions.demote_before_unban(*_ARGS)
    assert verdict is demote_actions.UnbanGate.DEMOTE_FAILED


@pytest.mark.parametrize("live_fails", [False, True])
@pytest.mark.asyncio
async def test_a_no_op_demote_blocks_a_surviving_role(
    monkeypatch: pytest.MonkeyPatch, *, live_fails: bool
) -> None:
    """A role that still resolves after a no-op demote blocks the unban."""

    async def _noop(*_args: Any, **_kwargs: Any) -> bool:
        return False

    async def _role(*_args: Any, **_kwargs: Any) -> str | None:
        if live_fails:
            raise RuntimeError("role lookup failed")
        return "moderator"

    monkeypatch.setattr(demote_actions.Demote, "execute", _noop)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)

    verdict = await demote_actions.demote_before_unban(*_ARGS)
    assert verdict is demote_actions.UnbanGate.ROLE_SURVIVED


@pytest.mark.asyncio
async def test_a_no_op_demote_with_no_role_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target whose role is already gone may be unbanned."""

    async def _noop(*_args: Any, **_kwargs: Any) -> bool:
        return False

    async def _role(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(demote_actions.Demote, "execute", _noop)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)

    verdict = await demote_actions.demote_before_unban(*_ARGS)
    assert verdict is demote_actions.UnbanGate.PROCEED


@pytest.mark.asyncio
async def test_cancellation_propagates_from_the_unban_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown is not a demote failure and must not become a verdict."""

    async def _cancelled(*_args: Any, **_kwargs: Any) -> bool:
        raise asyncio.CancelledError

    monkeypatch.setattr(demote_actions.Demote, "execute", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        await demote_actions.demote_before_unban(*_ARGS)
