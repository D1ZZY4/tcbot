# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The polling lifecycle must never report success without a live client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import __main__ as main_mod
from tcbot import notification_worker
from tcbot.database import mtproto as mtproto_mod
from tcbot.database import pg_cron
from tcbot.database import scheduler as sched_mod
from tcbot.modules.helper.pipelines import moderation_enforcement


class _Client:
    """Minimal client double with a configurable connection state."""

    def __init__(self, *, connected: bool) -> None:
        self.is_connected = connected


def _stub_startup(
    monkeypatch: pytest.MonkeyPatch, client: _Client, idled: list[bool]
) -> None:
    """Replace startup and shutdown work, leaving the lifecycle under test."""

    async def _ready(_client: Any) -> None:
        return None

    async def _false() -> bool:
        return False

    async def _start(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        return

    async def _shutdown() -> None:
        return None

    async def _idle() -> None:
        idled.append(True)

    monkeypatch.setattr(mtproto_mod, "client", lambda: client)
    monkeypatch.setattr(main_mod, "register_handlers", lambda _client: None)
    monkeypatch.setattr(main_mod, "init_shared_subsystems", _ready)
    monkeypatch.setattr(
        main_mod, "configure_moderation_enforcement", lambda _client: None
    )
    monkeypatch.setattr(main_mod, "configure_notification_worker", lambda _client: None)
    monkeypatch.setattr(pg_cron, "sync_schedules", _false)
    monkeypatch.setattr(sched_mod, "start", _start)
    monkeypatch.setattr(main_mod, "_shutdown_subsystems", _shutdown)
    monkeypatch.setattr(main_mod, "idle", _idle)

    def _discard(coro: Any) -> None:
        coro.close()

    monkeypatch.setattr(main_mod, "_startup_tasks", SimpleNamespace(spawn=_discard))
    monkeypatch.setattr(moderation_enforcement, "configure", lambda _bot: None)
    monkeypatch.setattr(notification_worker, "configure", lambda _bot: None)


def test_a_disconnected_client_fails_the_polling_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must not exit cleanly when the client dropped before polling."""
    idled: list[bool] = []
    _stub_startup(monkeypatch, _Client(connected=False), idled)

    with pytest.raises(RuntimeError, match="disconnected before the polling loop"):
        asyncio.run(main_mod._run_polling())

    assert idled == []


def test_a_connected_client_enters_the_polling_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary startup still reaches idle() with a live client."""
    idled: list[bool] = []
    _stub_startup(monkeypatch, _Client(connected=True), idled)

    asyncio.run(main_mod._run_polling())

    assert idled == [True]
