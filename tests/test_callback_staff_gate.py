# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Callback staff gates acknowledge, fail closed, and never swallow cancellation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper import guards
from tcbot.modules.helper.rich.button import ANONYMOUS_BOT_ID


class _Query:
    def __init__(self) -> None:
        self.answers: int = 0
        self.edits: list[tuple[str, str]] = []

    async def answer(self, *_args: Any, **_kwargs: Any) -> None:
        self.answers += 1


def _wire(monkeypatch: pytest.MonkeyPatch, role: Any = "admin") -> _Query:
    """Patch the gate's I/O, returning the query that collects its effects."""
    query = _Query()
    calls: list[str] = []

    async def _role(_uid: int, *, fresh: bool = False) -> str:
        calls.append("role")
        if isinstance(role, BaseException):
            raise role
        return role

    async def _locale(_ctx: Any) -> str:
        return "en-US"

    async def _edit(_q: Any, text: str, **kwargs: Any) -> None:
        query.edits.append((str(text), str(kwargs.get("log_label"))))

    monkeypatch.setattr(guards.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(guards, "locale_for_update", _locale)
    monkeypatch.setattr(guards, "cb_error_edit", _edit)
    monkeypatch.setattr(guards, "answer_ack", query.answer)
    query.role_reads = calls  # type: ignore[attr-defined]
    return query


def test_anonymous_admin_is_refused_without_a_role_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The placeholder must never reach the callback rank gate."""
    query = _wire(monkeypatch)
    admin = SimpleNamespace(id=ANONYMOUS_BOT_ID)

    result = asyncio.run(
        guards.check_callback_executor(object(), query, admin)  # type: ignore[arg-type]
    )

    assert result is None
    assert query.answers == 1
    assert query.edits[0][1] == "callback anon-admin"
    assert "personal account" in query.edits[0][0]
    assert query.role_reads == []  # type: ignore[attr-defined]


def test_a_missing_sender_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tap with no attributable user cannot authorize a role change."""
    query = _wire(monkeypatch)

    result = asyncio.run(
        guards.check_callback_executor(object(), query, None)  # type: ignore[arg-type]
    )

    assert result is None
    assert query.answers == 1
    assert query.edits[0][1] == "callback perm-expired"


def test_a_failed_role_lookup_is_a_perm_expired_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role outage must refuse the callback, not treat it as no role."""
    query = _wire(monkeypatch, RuntimeError("database down"))

    result = asyncio.run(
        guards.check_callback_executor(
            object(),  # type: ignore[arg-type]
            query,  # type: ignore[arg-type]
            SimpleNamespace(id=7),
        )
    )

    assert result is None
    assert query.answers == 1
    assert query.edits[0][1] == "callback perm-expired"


def test_a_staff_tap_passes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """An authorized admin gets the live role back for the caller."""
    query = _wire(monkeypatch)

    result = asyncio.run(
        guards.check_callback_executor(
            object(),  # type: ignore[arg-type]
            query,  # type: ignore[arg-type]
            SimpleNamespace(id=7),
        )
    )

    assert result == "admin"
    assert query.answers == 1
    assert query.edits == []


def test_cancellation_from_the_role_read_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown must cancel the gate instead of showing a refusal card."""
    query = _wire(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            guards.check_callback_staff(
                7,
                query,  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
            )
        )
