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
