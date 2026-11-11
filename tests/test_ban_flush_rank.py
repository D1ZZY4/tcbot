# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Silence-window ban flush must re-check executor rank before enforcing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import ban_flow
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
) -> ban_flow._ProofSession:
    now = monotonic()
    return ban_flow._ProofSession(
        msgs=[object()],  # type: ignore[list-item]
        meta={"ban_target_id": target_id, "ban_admin_id": admin_id},
        scope=_prefilled_scope(),
        last_arrival=now - 1000.0,
        deadline=now + 60.0,
    )


def _run_flush(
    monkeypatch: pytest.MonkeyPatch,
    session: ban_flow._ProofSession,
) -> tuple[dict[tuple[int, int], Any], list[Any]]:
    key = (11, 22)
    registry: dict[tuple[int, int], Any] = {}
    executed: list[Any] = []
    _install_fast_sleep(monkeypatch)
    monkeypatch.setattr(ban_flow, "_proof_sessions", registry)

    async def _fake_execute(bot: Any, msgs: Any, meta: Any) -> None:
        executed.append((bot, msgs, meta))

    monkeypatch.setattr(ban_flow, "_execute_ban", _fake_execute)

    async def _scenario() -> None:
        registry[key] = session
        await ban_flow._flush_session(key, _DummyBot())  # type: ignore[arg-type]

    asyncio.run(_scenario())
    return registry, executed


def test_flush_executes_when_executor_still_developer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _developer(uid: int, *, fresh: bool = False) -> str | None:
        return "developer"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _developer)
    registry, executed = _run_flush(monkeypatch, _session())
    assert len(executed) == 1
    assert registry == {}


def test_flush_aborts_when_executor_demoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _tester(uid: int, *, fresh: bool = False) -> str | None:
        return "tester"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _tester)
    registry, executed = _run_flush(monkeypatch, _session())
    assert executed == []
    assert registry == {}


def test_flush_fail_closed_on_role_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(uid: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    registry, executed = _run_flush(monkeypatch, _session())
    assert executed == []
    assert registry == {}


def test_flush_propagates_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cancelled(uid: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_effective_role", _cancelled)
    key = (11, 22)
    registry: dict[tuple[int, int], Any] = {}
    session = _session()
    _install_fast_sleep(monkeypatch)
    monkeypatch.setattr(ban_flow, "_proof_sessions", registry)

    async def _scenario() -> None:
        registry[key] = session
        await ban_flow._flush_session(key, _DummyBot())  # type: ignore[arg-type]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_scenario())
    # * Finally still clears the claimed session even on cancellation.
    assert registry == {}
