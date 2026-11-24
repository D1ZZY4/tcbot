# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shutdown drain must never cancel a proof flush that began enforcing."""

from __future__ import annotations

import asyncio

import pytest

from tcbot.modules.helper.pipelines import proof_session
from tcbot.modules.helper.pipelines.proof_session import (
    ProofSession,
    ProofSessionRegistry,
)


def test_drain_keeps_a_flush_that_crossed_into_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ban already executing must survive the shutdown grace window."""
    monkeypatch.setattr(proof_session, "_PROOF_DRAIN_TIMEOUT_S", 0.01)
    registry = ProofSessionRegistry()
    session = ProofSession()

    async def _cross_over() -> None:
        await asyncio.sleep(0)
        session.flushing = True
        await asyncio.sleep(30)

    async def _scenario() -> None:
        task = asyncio.create_task(_cross_over())
        session.flush_task = task
        registry.add((1, 2), session)
        await asyncio.sleep(0)
        await registry.drain()
        assert session.flushing is True
        assert not task.cancelled()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_scenario())


def test_drain_cancels_a_session_still_in_its_silence_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session that never started enforcing is still cancelled promptly."""
    monkeypatch.setattr(proof_session, "_PROOF_DRAIN_TIMEOUT_S", 0.01)
    registry = ProofSessionRegistry()
    session = ProofSession()

    async def _wait_forever() -> None:
        await asyncio.Event().wait()

    async def _scenario() -> None:
        task = asyncio.create_task(_wait_forever())
        session.flush_task = task
        registry.add((1, 2), session)
        await registry.drain()
        assert task.cancelled()

    asyncio.run(_scenario())


def test_drain_waits_for_execution_even_with_an_idle_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight ban receives its grace window alongside an idle session.

    A mixed registry used to take the branch that only awaited idle sessions,
    returning while a ban was still uploading proof and writing its record.
    """
    monkeypatch.setattr(proof_session, "_PROOF_DRAIN_TIMEOUT_S", 1.0)
    registry = ProofSessionRegistry()
    executing = ProofSession(flushing=True)
    short_wait = ProofSession()
    finished = asyncio.Event()

    async def _enforcing() -> None:
        await asyncio.sleep(0.08)
        finished.set()

    async def _finishing_soon() -> None:
        await asyncio.sleep(0.01)

    async def _scenario() -> None:
        exec_task = asyncio.create_task(_enforcing())
        wait_task = asyncio.create_task(_finishing_soon())
        executing.flush_task = exec_task
        short_wait.flush_task = wait_task
        registry.add((1, 2), executing)
        registry.add((3, 4), short_wait)

        await registry.drain()

        # * The idle session finishes first. The old implementation returned
        # * at that point and never gave the executing flush its grace window.
        assert finished.is_set(), "drain returned before the in-flight ban finished"
        assert not exec_task.cancelled()
        assert wait_task.done()
        await asyncio.gather(exec_task, return_exceptions=True)

    asyncio.run(_scenario())


def test_drain_cancels_only_idle_sessions_in_a_mixed_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long-running idle session is cancelled; an executing one is not."""
    monkeypatch.setattr(proof_session, "_PROOF_DRAIN_TIMEOUT_S", 0.02)
    registry = ProofSessionRegistry()
    executing = ProofSession(flushing=True)
    idle = ProofSession()

    async def _enforcing() -> None:
        await asyncio.sleep(30)

    async def _waiting() -> None:
        await asyncio.Event().wait()

    async def _scenario() -> None:
        exec_task = asyncio.create_task(_enforcing())
        wait_task = asyncio.create_task(_waiting())
        executing.flush_task = exec_task
        idle.flush_task = wait_task
        registry.add((1, 2), executing)
        registry.add((3, 4), idle)

        await registry.drain()

        assert not exec_task.cancelled()
        assert wait_task.cancelled()
        for task in (exec_task, wait_task):
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_scenario())
