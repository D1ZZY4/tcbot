# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn expiry: partial failure must surface as a job failure."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import scheduler as jobs


class _FakeResult:
    deleted_count = 3


class _FakeCollection:
    def __init__(self, *, should_fail: bool) -> None:
        self._should_fail = should_fail

    def delete_many(self, filt: dict[str, Any]) -> _FakeResult:
        if self._should_fail:
            raise RuntimeError("delete failed")
        return _FakeResult()


def _patch(monkeypatch: pytest.MonkeyPatch, *, fail_counts: bool) -> None:
    async def _db_call(op: Any, **_kwargs: Any) -> Any:
        return op()

    monkeypatch.setattr(jobs, "_db_call", _db_call)
    monkeypatch.setattr(
        jobs,
        "_col",
        lambda name: _FakeCollection(should_fail=fail_counts and name == "warn_counts"),
    )


def test_expire_success_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, fail_counts=False)
    asyncio.run(jobs.expire_old_warns(7))


def test_expire_partial_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, fail_counts=True)
    with pytest.raises(RuntimeError, match="incomplete"):
        asyncio.run(jobs.expire_old_warns(7))
