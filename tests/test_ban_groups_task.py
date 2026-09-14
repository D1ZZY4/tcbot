# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor cleanup: a propagated error must cancel and retrieve _groups_task."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.helper.workflows import ban_flow


class _DummyBot:
    username = "testbot"


def _fake_meta() -> dict[str, Any]:
    return {
        "ban_target_id": 33,
        "ban_target_fname": "Target",
        "ban_reason": "spam",
        "ban_admin_id": 44,
        "ban_admin_fname": "Mod",
        "ban_prompt_msg_id": 1,
        "ban_prompt_chat_id": 2,
        "ban_locale": "en",
    }


async def _stub_locale(*args: Any, **kwargs: Any) -> str:
    return "en"


def _install_create_task_spy(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task]:
    """Record tasks created via the module's asyncio.create_task reference while
    still delegating to the real scheduler.

    ``active_groups`` is stubbed to a long-running coroutine so the recorded
    task is still pending when the ban DB call raises, proving the cancel path.
    """
    created: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    async def _long_running() -> list:
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(ban_flow.db.groups_db, "active_groups", _long_running)

    def _spy(coro: Any, *args: Any, **kwargs: Any) -> asyncio.Task:
        task = real_create_task(coro, *args, **kwargs)
        created.append(task)
        return task

    monkeypatch.setattr(ban_flow.asyncio, "create_task", _spy)
    return created


def test_propagated_error_retrieves_groups_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("mongo down")

    monkeypatch.setattr(ban_flow, "locale_for_user", _stub_locale)
    monkeypatch.setattr(ban_flow.db.bans_db, "get_active_ban", _boom)
    created = _install_create_task_spy(monkeypatch)

    with pytest.raises(RuntimeError, match="mongo down"):
        asyncio.run(ban_flow._execute_ban(_DummyBot(), [], _fake_meta()))  # type: ignore[arg-type]

    assert len(created) == 1
    assert created[0].done()
    assert created[0].cancelled()


def test_cancellation_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cancel(*args: Any, **kwargs: Any) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(ban_flow, "locale_for_user", _stub_locale)
    monkeypatch.setattr(ban_flow.db.bans_db, "get_active_ban", _cancel)
    created = _install_create_task_spy(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ban_flow._execute_ban(_DummyBot(), [], _fake_meta()))  # type: ignore[arg-type]

    assert len(created) == 1
    assert created[0].done()
    assert created[0].cancelled()
