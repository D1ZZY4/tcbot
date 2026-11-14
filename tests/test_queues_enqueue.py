# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enqueue duplicate handling against a real PostgreSQL server.

The queue rejects two different duplicates: the random request id and the
one-pending-request-per-user rule. The database reports both as the same
error type, so the code tells them apart by the violated constraint
name. Only a real server proves that the two constraints keep their
names and that the retry logic reacts to the right one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tcbot.database import engine as engine_module
from tcbot.database import queues_db
from tcbot.database.queues_db import AlreadyPendingError, DuplicateKeyError
from tests.postgres_support import reset_community, seed_promotion_request, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def queue_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty promotion-queue table."""
    await reset_community()
    await seed_users(1, 7, 9, 42, 99)
    yield postgres_db
    await reset_community()


def _stub_ids(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> list[str]:
    """Return the request ids the queue will draw, in order."""
    calls: list[str] = []
    values = iter(ids)

    def _fake(length: int = 10) -> str:
        value = next(values)
        calls.append(value)
        return value

    monkeypatch.setattr(queues_db, "make_short_id", _fake)
    return calls


async def _seed(request_id: str, target_id: int, status: str = "pending") -> None:
    """Insert one promotion request straight into the table."""
    await seed_promotion_request(request_id, target_id, status=status)


async def test_collision_retries_once_then_succeeds(
    queue_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A taken request id is redrawn once instead of failing the request."""
    await _seed("first", 99)
    id_calls = _stub_ids(monkeypatch, ["first", "second"])

    result = await queues_db.enqueue(7, None, "Target", 1)

    assert result == "second"
    assert id_calls == ["first", "second"]
    stored = await queues_db.get_request_by_id("second")
    assert stored is not None
    assert stored.get("target_user_id") == 7


async def test_pending_violation_short_circuits_without_retry(
    queue_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second pending request for the same target is refused at once."""
    await _seed("taken", 7)
    id_calls = _stub_ids(monkeypatch, ["only"])

    with pytest.raises(AlreadyPendingError) as exc_info:
        await queues_db.enqueue(7, None, "Target", 1)

    assert isinstance(exc_info.value, DuplicateKeyError)
    assert engine_module.constraint_name(exc_info.value) == (
        "uq_promotion_requests_pending_target"
    )
    assert id_calls == ["only"]


async def test_second_failure_propagates(
    queue_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second id collision is reported instead of retried forever."""
    await _seed("first", 99)
    id_calls = _stub_ids(monkeypatch, ["first", "first"])

    with pytest.raises(DuplicateKeyError) as exc_info:
        await queues_db.enqueue(7, None, "Target", 1)

    assert not isinstance(exc_info.value, AlreadyPendingError)
    assert engine_module.constraint_name(exc_info.value) == (
        "uq_promotion_requests_request_id"
    )
    assert id_calls == ["first", "first"]


async def test_a_resolved_request_does_not_block_a_new_one(
    queue_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pending rule only covers the pending rows."""
    await _seed("old", 7, status="rejected")
    _stub_ids(monkeypatch, ["new"])

    result = await queues_db.enqueue(7, None, "Target", 1)

    assert result == "new"
