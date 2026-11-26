# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Logger hygiene: percent formatting, single emission, and safe time conversion."""

from __future__ import annotations

import logging
import sys

import pytest
from loguru import logger as loguru_logger

from tcbot import utils
from tcbot.utils.logger import (
    BotLogFormatter,
    _format_percent,
    _safe_time_parts,
    get_logger,
    set_record_sink,
    set_text_scrubber,
    setup,
)


def test_setup_registers_one_loguru_sink() -> None:
    """Loguru forwards every record exactly once.

    The bridge hands the record to the stdlib handlers, which own the
    console format and the Telegram shipping. A second Loguru console
    sink printed every line twice, once as Loguru markup and once as the
    bracket format.
    """
    setup()
    handlers = loguru_logger._core.handlers  # type: ignore[reportAttributeAccessIssue]
    assert len(handlers) == 1


def test_format_percent_happy_path() -> None:
    assert _format_percent("hello %s", ("world",)) == "hello world"
    assert _format_percent("hello", ()) == "hello"


def test_format_percent_mismatch_falls_back() -> None:
    out = _format_percent("value %s %s", ("x",))
    assert "value" in out and "('x',)" in out


def test_format_percent_type_mismatch_falls_back() -> None:
    out = _format_percent("count %d", ("not-int",))
    assert "count %d" in out and "not-int" in out


def test_shim_never_raises_on_bad_format(caplog: object) -> None:
    log = get_logger("test.logger.hygiene")
    log.info("count %d", "not-int")


def test_safe_time_parts_epoch() -> None:
    assert _safe_time_parts(0) == ("00:00", "01/01/70")


def test_safe_time_parts_bad_timestamp_falls_back() -> None:
    assert _safe_time_parts(float("inf")) == ("--:--", "--/--/--")


def test_formatter_handles_bad_timestamp() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    record.created = float("inf")
    out = BotLogFormatter().format(record)
    assert "hello" in out


def test_a_failing_sink_warning_reaches_stdlib_without_loguru_reentry(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sink outage must not vanish into Loguru's internal error dump."""
    setup()

    def _boom(_record: logging.LogRecord) -> None:
        raise RuntimeError("sink down")

    previous = utils.logger._record_sink
    set_record_sink(_boom)
    try:
        with caplog.at_level(logging.WARNING, logger="tcbot.utils.logger"):
            loguru_logger.error("trigger")
    finally:
        set_record_sink(previous)

    assert "Error log sink failed: sink down" in caplog.text
    assert "Logging error in Loguru" not in capsys.readouterr().err


def test_formatter_handles_bad_percent_args() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "count %d", ("not-int",), None
    )
    out = BotLogFormatter().format(record)
    assert "count" in out


def test_formatter_redacts_credentials_in_the_message() -> None:
    """A secret-shaped value in a log message never reaches the console."""
    token = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    record = logging.LogRecord(
        "t", logging.ERROR, __file__, 1, f"login {token}", None, None
    )
    out = BotLogFormatter().format(record)
    assert token not in out
    assert "[REDACTED_TOKEN]" in out

    url_record = logging.LogRecord(
        "t", logging.ERROR, __file__, 1, "postgresql://user:hunter2@host/db", None, None
    )
    assert "hunter2" not in BotLogFormatter().format(url_record)


def test_formatter_uses_the_registered_exact_value_scrubber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact configured values are masked before a console line is emitted."""
    _ = monkeypatch
    previous = utils.logger._text_scrubber
    marker = "exact-secret-marker"
    set_text_scrubber(lambda text: text.replace(marker, "[REDACTED]"))
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, marker, None, None)
        assert marker not in BotLogFormatter().format(record)
    finally:
        set_text_scrubber(previous)


def test_formatter_redacts_credentials_in_the_traceback() -> None:
    """An exception message is redacted at the single console output border."""
    token = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    try:
        raise RuntimeError(f"login failed for {token}")
    except RuntimeError:
        record = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "handler failed", None, sys.exc_info()
        )
    out = BotLogFormatter().format(record)
    assert token not in out
    assert "RuntimeError" in out
