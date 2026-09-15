# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban proof-flush cleanup race: a stale flush task must not clear a successor session."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from telegram import Chat, Message

from tcbot import database as db
from tcbot.modules.helper.workflows import ban_flow
from tcbot.utils.time_and_date import monotonic


class _DummyBot:
    username = "testbot"


class _FakeCallbackQuery:
    async def answer(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeChat:
    id = 11
    type = "supergroup"


class _FakeUser:
    id = 22


class _FakeUpdate:
    def __init__(self) -> None:
        self.effective_chat = _FakeChat()
        self.effective_user = _FakeUser()
        # * Real Message: on_done_proof narrows to Message before the
        # * rank re-check (inaccessible messages abort the tap).
        self.effective_message = Message(
            message_id=5,
            date=datetime.now(UTC),
            chat=Chat(id=_FakeChat.id, type=_FakeChat.type),
        )
        self.callback_query = _FakeCallbackQuery()


class _FakeCtx:
    def __init__(self, user_data: dict[str, Any]) -> None:
        self.user_data = user_data
        self.bot = _DummyBot()  # type: ignore[assignment]


def _prefilled_user_data() -> dict[str, Any]:
    return dict.fromkeys(ban_flow._BAN_USER_DATA_KEYS, "value")


def _install_flush_sleep_spy(
    monkeypatch: pytest.MonkeyPatch, events: list[asyncio.Event]
) -> None:
    """Route the module's asyncio.sleep calls through caller-provided gates."""
    real_sleep = asyncio.sleep
    index = 0

    async def _spy(delay: float, *args: Any, **kwargs: Any) -> None:
        nonlocal index
        if delay == 0:
            await real_sleep(0)
            return
        await events[index].wait()
        index += 1

    monkeypatch.setattr(ban_flow.asyncio, "sleep", _spy)


def _flush_sleep_scenario(
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_successor: bool,
) -> tuple[dict[tuple[int, int], Any], ban_flow._ProofSession | None]:
    """Run the real ``_flush_session`` up to a bound session, cancel it while the
    key may hold a successor, and return the registry plus the surviving session."""
    key = (11, 22)
    now = monotonic()
    first = ban_flow._ProofSession(
        user_data=_prefilled_user_data(),
        last_arrival=now,
        deadline=now + 60,
    )
    successor = None
    if with_successor:
        successor = ban_flow._ProofSession(
            user_data=_prefilled_user_data(),
            last_arrival=now,
            deadline=now + 60,
        )

    events = [asyncio.Event() for _ in range(2)]
    _install_flush_sleep_spy(monkeypatch, events)
    registry: dict[tuple[int, int], Any] = {}
    monkeypatch.setattr(ban_flow, "_proof_sessions", registry)

    async def _scenario() -> tuple[dict[tuple[int, int], Any], Any]:
        registry[key] = first
        task = asyncio.create_task(ban_flow._flush_session(key, _DummyBot()))  # type: ignore[arg-type]
        await asyncio.sleep(0)
        events[0].set()
        await asyncio.sleep(0)
        first.flushing = True
        task.cancel()
        if successor is not None:
            registry.pop(key, None)
            ban_flow._clear_ban_state(first.user_data)
            registry[key] = successor
        events[1].set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("_flush_session should have been cancelled")
        return registry, successor

    return asyncio.run(_scenario())


def test_flush_finally_does_not_clear_successor_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, successor = _flush_sleep_scenario(monkeypatch, with_successor=True)
    assert successor is not None
    assert registry[(_FakeChat.id, _FakeUser.id)] is successor
    assert successor.user_data == _prefilled_user_data()


def test_flush_finally_clears_own_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, successor = _flush_sleep_scenario(monkeypatch, with_successor=False)
    assert successor is None
    assert registry == {}


def test_done_proof_finally_guard_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = (_FakeChat.id, _FakeUser.id)
    first = ban_flow._ProofSession(
        msgs=[object()],  # type: ignore[list-item]
        meta={"ban_target_id": 33, "ban_admin_id": 44},
        user_data=_prefilled_user_data(),
    )
    successor = ban_flow._ProofSession(user_data=_prefilled_user_data())
    registry: dict[tuple[int, int], Any] = {}
    monkeypatch.setattr(ban_flow, "_proof_sessions", registry)

    async def _replace_while_executing(*args: Any, **kwargs: Any) -> None:
        registry.pop(key, None)
        ban_flow._clear_ban_state(first.user_data)
        registry[key] = successor

    async def _scenario() -> object:
        registry[key] = first
        monkeypatch.setattr(ban_flow, "_execute_ban", _replace_while_executing)

        async def _founder(uid: int) -> str | None:
            return "founder"

        monkeypatch.setattr(db.users_roles, "get_effective_role", _founder)
        return await ban_flow.on_done_proof(
            _FakeUpdate(),  # type: ignore[arg-type]
            _FakeCtx(first.user_data),  # type: ignore[arg-type]
        )

    outcome = asyncio.run(_scenario())
    assert outcome == ban_flow.ConversationHandler.END
    assert registry[key] is successor
    assert successor.user_data == _prefilled_user_data()
