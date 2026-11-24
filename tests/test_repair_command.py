# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The staff repair command lists and re-drives enforcement runs."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import enforcement_db
from tcbot.modules import maintenance


class _Message:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append(text)


async def _locale(update: Any) -> str:
    return "en-US"


def _run(**overrides: Any) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 42,
        "operation": "apply",
        "action_type": "ban",
        "target_user_id": 900,
        "status": "failed",
        "succeeded_count": 1,
        "skipped_count": 0,
        "failed_count": 1,
        "target_count": 2,
        "exhausted_targets": 1,
    }
    row.update(overrides)
    return row


def test_repair_lines_name_the_run_and_the_failed_groups() -> None:
    text = maintenance._repair_lines([_run()], "en-US")

    assert "42" in text
    assert "ban" in text
    assert "1/2 applied" in text
    assert "1 exhausted" in text
    assert "<p>" in text
    assert "\n" not in text


def test_tcrepair_lists_the_unsettled_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list() -> list[dict[str, object]]:
        return [_run()]

    monkeypatch.setattr(maintenance.db.enforcement_db, "list_unsettled_runs", _list)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _owner(*, fresh: bool = False) -> int:
        return 1

    monkeypatch.setattr(maintenance.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)

    message = _Message("/tcrepair")
    ctx = SimpleNamespace(
        bot=object(),
        effective_message=message,
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
        effective_chat=None,
        user_data={},
    )
    asyncio.run(inspect.unwrap(maintenance.cmd_repair)(ctx))

    assert message.replies
    assert "42" in message.replies[-1]


def test_tcrepair_retries_one_run_through_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int, int | None]] = []
    delivered: list[int] = []

    async def _redrive(run_id: int, *, chat_id: int | None = None) -> Any:
        seen.append((run_id, chat_id))
        return enforcement_db.RepairResult("queued", 2)

    async def _deliver(bot: Any, run_id: int) -> bool:
        delivered.append(run_id)
        return True

    monkeypatch.setattr(maintenance.db.enforcement_db, "redrive_run", _redrive)
    monkeypatch.setattr(maintenance.enforcement_worker, "deliver_queued_run", _deliver)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _owner(*, fresh: bool = False) -> int:
        return 1

    monkeypatch.setattr(maintenance.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)

    message = _Message("/tcrepair retry 42 -1001")
    ctx = SimpleNamespace(
        bot=object(),
        effective_message=message,
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
        effective_chat=None,
        user_data={},
    )
    asyncio.run(inspect.unwrap(maintenance.cmd_repair)(ctx))

    assert seen == [(42, -1001)]
    assert delivered == [42]
    assert message.replies
    assert "2" in message.replies[-1]


def test_tcrepair_rejects_an_incomplete_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _redrive(run_id: int, *, chat_id: int | None = None) -> Any:
        raise AssertionError("a malformed command must not touch the ledger")

    monkeypatch.setattr(maintenance.db.enforcement_db, "redrive_run", _redrive)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _owner(*, fresh: bool = False) -> int:
        return 1

    monkeypatch.setattr(maintenance.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)

    message = _Message("/tcrepair retry")
    ctx = SimpleNamespace(
        bot=object(),
        effective_message=message,
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
        effective_chat=None,
        user_data={},
    )
    asyncio.run(inspect.unwrap(maintenance.cmd_repair)(ctx))

    assert message.replies
    assert "Usage" in message.replies[-1]
