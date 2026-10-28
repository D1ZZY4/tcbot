# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared chat-repoint helper: matched-return, failure, and cancellation semantics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot.database import _migration


async def _identity(coro: Any) -> Any:
    return await coro


class _FakeCollection:
    def __init__(self, outcome: BaseException | None = None, matched: int = 1) -> None:
        self.outcome = outcome
        self.matched = matched
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def update_many(self, filt: dict[str, Any], update: dict[str, Any]) -> Any:
        self.calls.append((filt, update))
        if self.outcome is not None:
            raise self.outcome
        return SimpleNamespace(matched_count=self.matched)


_LOG_MSG = "test (_migration) (%d -> %d) failed"


def _call(collection: _FakeCollection) -> bool:
    return asyncio.run(
        _migration._repoint_chat(cast("Any", collection), 10, 20, log_msg=_LOG_MSG)
    )


def test_repoint_repoints_chat_and_returns_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _FakeCollection(matched=3)
    monkeypatch.setattr(_migration, "db_call", _identity)

    result = _call(collection)

    assert result is True
    assert collection.calls == [({"chat_id": 10}, {"$set": {"chat_id": 20}})]


def test_repoint_zero_matched_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_migration, "db_call", _identity)

    result = _call(_FakeCollection(matched=0))

    assert result is False


def test_repoint_generic_failure_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _FakeCollection(outcome=RuntimeError("db blip"))
    monkeypatch.setattr(_migration, "db_call", _identity)

    result = _call(collection)

    assert result is False
    assert len(collection.calls) == 1


def test_repoint_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _FakeCollection(outcome=asyncio.CancelledError())
    monkeypatch.setattr(_migration, "db_call", _identity)

    async def _run_coro() -> None:
        with pytest.raises(asyncio.CancelledError):
            await _migration._repoint_chat(
                cast("Any", collection), 10, 20, log_msg=_LOG_MSG
            )

    asyncio.run(_run_coro())
    assert collection.calls == [({"chat_id": 10}, {"$set": {"chat_id": 20}})]
