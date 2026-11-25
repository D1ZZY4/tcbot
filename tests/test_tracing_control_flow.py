# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Dispatcher hand-off is control flow, not an error to report."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation

from tcbot.modules.helper.decorators.tracing import log_execution


def test_continue_propagation_stays_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    """A handler that does not own an update must not emit an ERROR trace."""

    @log_execution
    async def _handler(ctx: Any) -> None:
        _ = ctx
        raise ContinuePropagation()

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(ContinuePropagation),
    ):
        asyncio.run(
            _handler(
                SimpleNamespace(effective_user=None, effective_chat=None, update_id=1)
            )
        )

    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert any("passed on after" in record.getMessage() for record in caplog.records)


def test_a_real_exception_still_logs_at_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only the dispatcher signal is reclassified; real failures stay loud."""

    @log_execution
    async def _handler(ctx: Any) -> None:
        _ = ctx
        raise RuntimeError("genuine failure")

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(RuntimeError, match="genuine failure"),
    ):
        asyncio.run(
            _handler(
                SimpleNamespace(effective_user=None, effective_chat=None, update_id=2)
            )
        )

    assert any(
        record.levelno >= logging.ERROR and "raised after" in record.getMessage()
        for record in caplog.records
    )
