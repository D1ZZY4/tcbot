# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A cancelled rules publish must release its run lock."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import rules_publish as publish


@pytest.mark.asyncio
async def test_cancelled_publish_closes_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished: list[tuple[int, str]] = []
    started = asyncio.Event()

    async def _reclaim() -> None:
        return None

    async def _acquire(*_args: Any, **_kwargs: Any) -> int:
        return 77

    async def _finish(run_id: int, status: str, **_kwargs: Any) -> None:
        finished.append((run_id, status))

    async def _items(_version_id: int) -> list[dict[str, Any]]:
        started.set()
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(publish, "cfg", SimpleNamespace(main_channel=-100))
    monkeypatch.setattr(publish.rules_db.runs, "reclaim_expired", _reclaim)
    monkeypatch.setattr(publish.rules_db.runs, "acquire", _acquire)
    monkeypatch.setattr(publish.rules_db.runs, "finish", _finish)
    monkeypatch.setattr(publish.rules_db, "all_items", _items)

    task = asyncio.create_task(publish.publish_rules(1, 2, 3, object()))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert finished == [(77, "failed")]
