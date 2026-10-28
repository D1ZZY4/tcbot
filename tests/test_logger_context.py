# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Request-context logging: bound IDs render on every line until cleared."""

from __future__ import annotations

import logging
from typing import Any

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
