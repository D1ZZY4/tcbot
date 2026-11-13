# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role-resolution reads on the moderation authorization path."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper import guards


class _FakeMessage:
    """Minimal message double for the refusal replies."""

    def __init__(self) -> None:
        self.chat = type("Chat", (), {"type": "group", "id": -100})()
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append(text)


@pytest.fixture
def _recorded_reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    """Record every ``(user_id, fresh)`` pair the check helpers read."""
    reads: list[tuple[int, bool]] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        reads.append((user_id, fresh))
        # * The executor outranks the target, so the pair check passes.
        return "admin" if user_id == 100 else "tester"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(guards, "effective_locale", _fake_locale)
    return reads


async def _fake_locale(chat_type: str, user_id: int, chat_id: int) -> str:
    return "en-US"


async def test_both_roles_are_read_fresh(
    _recorded_reads: list[tuple[int, bool]],
) -> None:
    """The check reads both roles fresh, so it never depends on a decorator.

    The two reads run in parallel, so the fresh executor read costs no
    extra latency. It removes the implicit requirement that a tier
    decorator ran first and refreshed the role cache, which a future
    caller could not see.
    """
    msg = _FakeMessage()
    result = await guards.resolve_and_check(
        msg,  # type: ignore[arg-type]
        100,
        200,
        min_role="developer",
    )

    assert result == ("admin", "tester")
    executor_reads = [fresh for uid, fresh in _recorded_reads if uid == 100]
    target_reads = [fresh for uid, fresh in _recorded_reads if uid == 200]
    assert executor_reads == [True]
    assert target_reads == [True]


async def test_the_target_role_is_always_read_fresh(
    _recorded_reads: list[tuple[int, bool]],
) -> None:
    """A demotion of the target must never be hidden behind a cache TTL."""
    await guards.resolve_and_check(
        _FakeMessage(),  # type: ignore[arg-type]
        100,
        200,
        min_role="developer",
    )

    assert all(fresh for uid, fresh in _recorded_reads if uid == 200)


async def test_a_failed_target_lookup_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached executor must not turn a target outage into an approval."""

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        if user_id == 200:
            raise RuntimeError("database down")
        return "admin" if user_id == 100 else "tester"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(guards, "effective_locale", _fake_locale)

    msg = _FakeMessage()
    result = await guards.resolve_and_check(
        msg,  # type: ignore[arg-type]
        100,
        200,
        min_role="developer",
    )

    assert result == (None, None)
    assert msg.replies, "a lookup failure must produce a refusal reply"
