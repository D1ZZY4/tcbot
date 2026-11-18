# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Silence-window ban flush delegates rank enforcement to the ban executor."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import ban_flow
from tcbot.modules.helper.pipelines.proof_session import (
    ProofSession,
    ProofSessionRegistry,
)
from tcbot.utils.time_and_date import monotonic


class _DummyBot:
    username = "testbot"


def _prefilled_scope() -> dict[str, Any]:
    return dict.fromkeys(ban_flow.BAN_USER_DATA_KEYS, "value")


def _install_fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep

    async def _fast(delay: float, *args: Any, **kwargs: Any) -> None:
        await real_sleep(0)

    monkeypatch.setattr(ban_flow.asyncio, "sleep", _fast)


def _session(
    *,
    admin_id: int = 44,
    target_id: int = 33,
) -> ProofSession:
    now = monotonic()
    return ProofSession(
        msgs=[object()],  # type: ignore[list-item]
        meta={"ban_target_id": target_id, "ban_admin_id": admin_id},
        scope=_prefilled_scope(),
        last_arrival=now - 1000.0,
        deadline=now + 60.0,
    )


def _run_flush(
    monkeypatch: pytest.MonkeyPatch,
    session: ProofSession,
) -> tuple[ProofSessionRegistry, list[Any]]:
    key = (11, 22)
    registry = ProofSessionRegistry()
    executed: list[Any] = []
    _install_fast_sleep(monkeypatch)
    monkeypatch.setattr(ban_flow, "proof_sessions", registry)

    async def _fake_execute(bot: Any, msgs: Any, meta: Any) -> None:
        executed.append((bot, msgs, meta))

    monkeypatch.setattr(ban_flow, "_execute_ban", _fake_execute)

    async def _scenario() -> None:
        registry[key] = session
        await ban_flow._flush_session(key, _DummyBot())  # type: ignore[arg-type]

    asyncio.run(_scenario())
    return registry, executed


def test_flush_hands_the_session_to_the_ban_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor owns the rank gate; the flush only hands over the batch."""
    registry, executed = _run_flush(monkeypatch, _session())
    assert len(executed) == 1
    assert len(registry) == 0


def test_flush_releases_the_session_when_cancelled_during_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shutdown cancellation must not leave the proof session behind."""
    key = (11, 22)
    registry = ProofSessionRegistry()
    session = _session()
    monkeypatch.setattr(ban_flow, "proof_sessions", registry)

    async def _scenario() -> None:
        registry[key] = session
        task = asyncio.create_task(
            ban_flow._flush_session(key, _DummyBot())  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())
    assert len(registry) == 0
