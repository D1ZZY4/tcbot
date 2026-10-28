# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter upsert race: DuplicateKeyError retries without rolling back warns."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from tcbot.database.warns_db import counters, records


def _dup_error() -> DuplicateKeyError:
    return DuplicateKeyError(
        "E11000 duplicate key error collection: tcbot.warn_counts "
        "index: user_id_1_chat_id_1 dup key: { user_id: 42, chat_id: 5 }",
        11000,
        {
            "keyPattern": {"user_id": 1, "chat_id": 1},
            "keyValue": {"user_id": 42, "chat_id": 5},
        },
    )


async def _identity(coro: Any) -> Any:
    return await coro


class _FakeWarns:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.deleted: list[dict[str, Any]] = []

    async def insert_one(self, doc: dict[str, Any]) -> SimpleNamespace:
        self.inserted.append(dict(doc))
        return SimpleNamespace(inserted_id="warn-1")

    async def delete_one(self, filt: dict[str, Any]) -> SimpleNamespace:
        self.deleted.append(filt)
        return SimpleNamespace(deleted_count=1)


class _FakeWarnCounts:
    """Counter collection double: first upsert loses the race, retry wins."""

    def __init__(self) -> None:
        self.upsert_calls = 0

    async def find_one_and_update(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.upsert_calls += 1
        if self.upsert_calls == 1:
            raise _dup_error()
        # * Second attempt applies the ``$inc`` to the winner's doc: count 1.
        return {"count": 1}


def _patch_warns(monkeypatch: pytest.MonkeyPatch, warns: _FakeWarns) -> None:
    monkeypatch.setattr(records, "_warns", lambda: warns)


def _patch_counts(
    monkeypatch: pytest.MonkeyPatch,
    counts: object,
    *,
    db_call_identity: bool = True,
) -> None:
    monkeypatch.setattr(records, "_warn_counts", lambda: counts)
    monkeypatch.setattr(counters, "_warn_counts", lambda: counts)
    if db_call_identity:
        monkeypatch.setattr(records, "db_call", _identity)
        monkeypatch.setattr(counters, "db_call", _identity)


def test_add_warn_retries_upsert_without_rollback_on_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warns = _FakeWarns()
    counts = _FakeWarnCounts()
    _patch_warns(monkeypatch, warns)
    _patch_counts(monkeypatch, counts)

    result = asyncio.run(records.add_warn(42, "spam", 1, 5))

    assert result == 1
    assert counts.upsert_calls == 2
    assert len(warns.inserted) == 1
    assert warns.deleted == []


def test_add_warn_rolls_back_on_non_dup_counter_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warns = _FakeWarns()

    class _BoomCounts:
        async def find_one_and_update(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:
            raise RuntimeError("db blip")

    _patch_warns(monkeypatch, warns)
    _patch_counts(monkeypatch, _BoomCounts())

    with pytest.raises(RuntimeError):
        asyncio.run(records.add_warn(42, "spam", 1, 5))

    assert len(warns.inserted) == 1
    assert warns.deleted == [{"_id": "warn-1"}]


def test_sync_warn_count_backfill_race_returns_winner_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = iter([None, {"count": 7}])

    class _FakeWarns:
        async def count_documents(self, filt: dict[str, Any]) -> int:
            return 3

    class _FakeCounts:
        async def find_one(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            return next(reads)

        async def find_one_and_update(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:
            raise _dup_error()

    monkeypatch.setattr(counters, "_warns", lambda: _FakeWarns())
    monkeypatch.setattr(counters, "_warn_counts", lambda: _FakeCounts())
    monkeypatch.setattr(counters, "db_call", _identity)

    result = asyncio.run(counters._sync_warn_count(42, 5))

    assert result == 7


def test_sync_warn_count_backfill_race_falls_back_to_counted_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = iter([None, None])

    class _FakeWarns:
        async def count_documents(self, filt: dict[str, Any]) -> int:
            return 3

    class _FakeCounts:
        async def find_one(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            return next(reads)

        async def find_one_and_update(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:
            raise _dup_error()

    monkeypatch.setattr(counters, "_warns", lambda: _FakeWarns())
    monkeypatch.setattr(counters, "_warn_counts", lambda: _FakeCounts())
    monkeypatch.setattr(counters, "db_call", _identity)

    result = asyncio.run(counters._sync_warn_count(42, 5))

    assert result == 3


def test_inc_warn_count_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CancelledCounts:
        async def find_one_and_update(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:
            raise asyncio.CancelledError()

    monkeypatch.setattr(counters, "_warn_counts", lambda: _CancelledCounts())
    monkeypatch.setattr(counters, "db_call", _identity)

    async def _run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await counters._inc_warn_count(42, 5)

    asyncio.run(_run())
