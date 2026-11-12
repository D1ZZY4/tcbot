# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The compatibility logger follows the standard exception contract."""

from __future__ import annotations

import logging
from typing import Any

from tcbot.utils.logger import get_logger


def test_exception_attaches_the_handled_traceback(caplog: Any) -> None:
    """The default attaches the exception currently being handled."""
    log = get_logger("test.logger.exception")
    with caplog.at_level(logging.ERROR, logger="test.logger.exception"):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("failed")
    assert "failed" in caplog.text
    assert "ValueError" in caplog.text


def test_exception_without_exc_info_omits_the_traceback(caplog: Any) -> None:
    """``exc_info=False`` suppresses the traceback."""
    log = get_logger("test.logger.exception")
    with caplog.at_level(logging.ERROR, logger="test.logger.exception"):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("failed", exc_info=False)
    assert "failed" in caplog.text
    assert "ValueError" not in caplog.text
