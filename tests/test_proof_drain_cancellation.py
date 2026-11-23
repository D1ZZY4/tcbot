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
