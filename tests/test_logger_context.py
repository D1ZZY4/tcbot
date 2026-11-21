# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Request-context logging: binding, rendering, and decorator cleanup."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper.decorators import tracing
from tcbot.utils.logger import (
    BotLogFormatter,
    bind_request_context,
    clear_request_context,
    get_logger,
)


def _record() -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)


def test_context_segment_absent_without_binding() -> None:
    clear_request_context()
    assert "[u=" not in BotLogFormatter().format(_record())


def test_context_segment_renders_bound_ids() -> None:
    clear_request_context()
    bind_request_context(update_id=7, user_id=1, chat_id=-100)
    try:
        out = BotLogFormatter().format(_record())
    finally:
        clear_request_context()
    assert "u=1" in out and "c=-100" in out and "#7" in out
    assert "[u=" not in BotLogFormatter().format(_record())


def test_structlog_logger_reaches_caplog(caplog: Any) -> None:
    log = get_logger("test.logger.routing")
    with caplog.at_level(logging.INFO, logger="test.logger.routing"):
        log.info("hello structlog %s", "world")
    assert "hello structlog world" in caplog.text


def _wrapped_update() -> Any:
    return SimpleNamespace(
        update_id=1,
        effective_user=SimpleNamespace(id=2),
        effective_chat=SimpleNamespace(id=-3),
    )


async def test_log_execution_clears_context_after_success(monkeypatch: Any) -> None:
    """The tracer clears request IDs after a handler completes normally."""
    cleared: list[bool] = []
    monkeypatch.setattr(tracing, "clear_request_context", lambda: cleared.append(True))

    async def _ok(update: Any, ctx: Any) -> str:
        return "done"

    assert await tracing.log_execution(_ok)(_wrapped_update(), None) == "done"
    assert cleared == [True]


async def test_log_execution_clears_context_when_handler_raises(
    monkeypatch: Any,
) -> None:
    """The tracer clears request IDs even when a handler raises."""
    cleared: list[bool] = []
    monkeypatch.setattr(tracing, "clear_request_context", lambda: cleared.append(True))

    async def _boom(update: Any, ctx: Any) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await tracing.log_execution(_boom)(_wrapped_update(), None)

    assert cleared == [True]
