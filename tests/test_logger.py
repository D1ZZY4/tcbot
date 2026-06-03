# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for bot logging setup."""

from __future__ import annotations

import logging

from tcbot.utils import logger


def _remove_project_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if isinstance(handler, logger.TelegramErrorHandler) or isinstance(
            handler.formatter, logger.BotLogFormatter
        ):
            root.removeHandler(handler)
            handler.close()


def test_setup_is_idempotent_for_project_handlers() -> None:
    root = logging.getLogger()
    _remove_project_handlers(root)

    try:
        logger.setup(logging.DEBUG)
        logger.setup(logging.INFO)

        project_handlers = [
            handler
            for handler in root.handlers
            if isinstance(handler, logger.TelegramErrorHandler)
            or isinstance(handler.formatter, logger.BotLogFormatter)
        ]

        assert len(project_handlers) == 2
        assert (
            sum(
                isinstance(handler.formatter, logger.BotLogFormatter)
                for handler in project_handlers
            )
            == 1
        )
        assert (
            sum(
                isinstance(handler, logger.TelegramErrorHandler)
                for handler in project_handlers
            )
            == 1
        )
        assert root.level == logging.INFO
    finally:
        _remove_project_handlers(root)


def test_setup_preserves_existing_external_handlers() -> None:
    root = logging.getLogger()
    external_handler = logging.NullHandler()
    root.addHandler(external_handler)
    _remove_project_handlers(root)

    try:
        logger.setup(logging.WARNING)

        assert external_handler in root.handlers
    finally:
        _remove_project_handlers(root)
        root.removeHandler(external_handler)


def test_setup_sets_root_log_level() -> None:
    root = logging.getLogger()
    _remove_project_handlers(root)
    try:
        logger.setup(logging.DEBUG)
        assert root.level == logging.DEBUG
    finally:
        _remove_project_handlers(root)


def test_bot_log_formatter_format_returns_string() -> None:
    """BotLogFormatter.format must return a non-empty string."""
    formatter = logger.BotLogFormatter()
    record = logging.LogRecord(
        name="tcbot.test",
        level=logging.INFO,
        pathname="",
        lineno=1,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    result = formatter.format(record)
    assert isinstance(result, str)
    assert "hello world" in result


def test_bot_log_formatter_includes_level_label() -> None:
    formatter = logger.BotLogFormatter()
    for level, label in [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARN"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "CRIT"),
    ]:
        record = logging.LogRecord(
            name="tcbot.test",
            level=level,
            pathname="",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert label in result, f"Expected {label!r} in format output for level {level}"


def test_telegram_error_handler_level_is_error() -> None:
    handler = logger.TelegramErrorHandler()
    assert handler.level == logging.ERROR


def test_telegram_error_handler_emit_suppresses_known_prefix() -> None:
    """Emit must silently skip records from suppressed loggers."""
    handler = logger.TelegramErrorHandler()
    record = logging.LogRecord(
        name="httpcore.something",
        level=logging.ERROR,
        pathname="",
        lineno=1,
        msg="error",
        args=(),
        exc_info=None,
    )
    handler.emit(record)


def test_telegram_error_handler_emit_no_loop_silently_returns() -> None:
    """Emit must not crash when there is no running asyncio event loop."""
    handler = logger.TelegramErrorHandler()
    record = logging.LogRecord(
        name="tcbot.some_module",
        level=logging.ERROR,
        pathname="",
        lineno=1,
        msg="error",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
