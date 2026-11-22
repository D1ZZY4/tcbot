# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Direct coverage for the demote-before-enforcement safety gate.

The gate is security-critical: a lookup outage must never block federation
moderation, the protected Owner must never be demoted, and a failed demote
must still let enforcement proceed. Every caller stubs this helper, so the
branches need their own tests.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import demote_flow
from tcbot.modules.helper.pipelines.demote_flow import (
    Demote,
    demote_before_enforcement,
)


def _role(monkeypatch: pytest.MonkeyPatch, role: str | None) -> None:
    """Make the fresh role read return *role*."""

    async def _read(user_id: int, *, fresh: bool = False) -> str | None:
        return role

    monkeypatch.setattr(db.users_roles, "get_effective_role", _read)


def test_lookup_failure_proceeds_without_demote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database outage cannot halt moderation: the target is non-staff."""
    calls: list[str | None] = []

    async def _raise(user_id: int, *, fresh: bool = False) -> str:
        raise RuntimeError("db down")

    async def _execute(*args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs.get("trigger"))
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _raise)
    monkeypatch.setattr(Demote, "execute", staticmethod(_execute))
    result = asyncio.run(
        demote_before_enforcement(object(), 9, "Target", trigger="ban")  # type: ignore[arg-type]
    )
    assert result is None
    assert calls == []


def test_owner_is_never_demoted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protected Owner verdict reaches the caller without a demote."""
    calls: list[str | None] = []

    async def _execute(*args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs.get("trigger"))
        return True

    _role(monkeypatch, "owner")
    monkeypatch.setattr(Demote, "execute", staticmethod(_execute))
    result = asyncio.run(
        demote_before_enforcement(object(), 9, "Target", trigger="ban")  # type: ignore[arg-type]
    )
    assert result == "owner"
    assert calls == []


def test_demote_failure_still_returns_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed demote is logged but never blocks the moderation action."""
    calls: list[str | None] = []

    async def _execute(*args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs.get("trigger"))
        raise RuntimeError("demote failed")

    _role(monkeypatch, "admin")
    monkeypatch.setattr(Demote, "execute", staticmethod(_execute))
    result = asyncio.run(
        demote_before_enforcement(object(), 9, "Target", trigger="mute")  # type: ignore[arg-type]
    )
    # * None tells the caller to proceed with the target treated as non-staff.
    assert result is None
    assert calls == ["mute"]


def test_success_passes_trigger_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """The successful path demotes with the caller's trigger."""
    calls: list[str | None] = []

    async def _execute(*args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs.get("trigger"))
        return True

    _role(monkeypatch, "moderator")
    monkeypatch.setattr(Demote, "execute", staticmethod(_execute))
    result = asyncio.run(
        demote_before_enforcement(object(), 9, "Target", trigger="kick")  # type: ignore[arg-type]
    )
    assert result == "moderator"
    assert calls == ["kick"]


def test_enforcement_dm_uses_the_localized_verb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The demote DM must contain a real verb, not a missing-key marker."""
    sent: list[str] = []

    async def _removed(target_id: int) -> bool:
        return True

    async def _send_text(bot: Any, target_id: int, text: str, **kwargs: Any) -> None:
        sent.append(text)

    async def _send_log(bot: Any, text: str, **kwargs: Any) -> None:
        return None

    async def _locale(target_id: int) -> str:
        return "en-US"

    monkeypatch.setattr(Demote, "remove_role", staticmethod(_removed))
    monkeypatch.setattr(demote_flow, "send_text", _send_text)
    monkeypatch.setattr(demote_flow, "send_log", _send_log)
    monkeypatch.setattr(demote_flow, "locale_for_user", _locale)
    asyncio.run(
        Demote.execute(
            object(),  # type: ignore[arg-type]
            9,
            "Target",
            "admin",
            1,
            "Exec",
            trigger="ban",
        )
    )
    assert len(sent) == 1
    assert "banned" in sent[0]
    assert "[dm.verb" not in sent[0]
