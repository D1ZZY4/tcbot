# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enqueue duplicate handling: ID collisions retry once, pending violations do not."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from tcbot.database import queues_db
from tcbot.database.queues_db import AlreadyPendingError


class _FakeRequests:
    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self._outcomes = list(outcomes)
        self.docs: list[dict[str, Any]] = []
        self.calls = 0

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if outcome is not None:
            raise outcome
        self.docs.append(dict(doc))


async def _identity(coro: Any) -> Any:
    return await coro


def _collision_error(request_id: str) -> DuplicateKeyError:
    return DuplicateKeyError(
        f'E11000 duplicate key error collection: tcbot.promotion_requests index: request_id_1 dup key: {{ request_id: "{request_id}" }}',
        11000,
        {"keyPattern": {"request_id": 1}, "keyValue": {"request_id": request_id}},
    )


def _pending_error(user_id: int) -> DuplicateKeyError:
    return DuplicateKeyError(
        f"E11000 duplicate key error collection: tcbot.promotion_requests index: target_id_1 dup key: {{ target_id: {user_id} }}",
        11000,
        {"keyPattern": {"target_id": 1}, "keyValue": {"target_id": user_id}},
    )


def _stub_ids(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> list[str]:
    calls: list[str] = []
    values = iter(ids)

    def _fake(length: int = 10) -> str:
        value = next(values)
        calls.append(value)
        return value

    monkeypatch.setattr(queues_db, "make_short_id", _fake)
    return calls


def test_collision_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRequests([_collision_error("first"), None])
    monkeypatch.setattr(queues_db, "_requests", lambda: fake)
    monkeypatch.setattr(queues_db, "db_call", _identity)
    id_calls = _stub_ids(monkeypatch, ["first", "second"])

    result = asyncio.run(queues_db.enqueue(7, None, "Target", 1))

    assert result == "second"
    assert id_calls == ["first", "second"]
    assert fake.calls == 2
    assert [doc["request_id"] for doc in fake.docs] == ["second"]


def test_pending_violation_short_circuits_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRequests([_pending_error(7)])
    monkeypatch.setattr(queues_db, "_requests", lambda: fake)
    monkeypatch.setattr(queues_db, "db_call", _identity)
    id_calls = _stub_ids(monkeypatch, ["only"])

    with pytest.raises(AlreadyPendingError) as exc_info:
        asyncio.run(queues_db.enqueue(7, None, "Target", 1))

    assert isinstance(exc_info.value, DuplicateKeyError)
    assert id_calls == ["only"]
    assert fake.calls == 1
    assert fake.docs == []


def test_second_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests([_collision_error("first"), _collision_error("second")])
    monkeypatch.setattr(queues_db, "_requests", lambda: fake)
    monkeypatch.setattr(queues_db, "db_call", _identity)
    id_calls = _stub_ids(monkeypatch, ["first", "second"])

    with pytest.raises(DuplicateKeyError) as exc_info:
        asyncio.run(queues_db.enqueue(7, None, "Target", 1))

    assert not isinstance(exc_info.value, AlreadyPendingError)
    assert id_calls == ["first", "second"]
    assert fake.calls == 2
    assert fake.docs == []
