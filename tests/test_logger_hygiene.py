# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Logger hygiene: percent formatting and time conversion never raise."""

from __future__ import annotations

import logging

from tcbot.utils.logger import (
    BotLogFormatter,
    _format_percent,
    _safe_time_parts,
    get_logger,
)


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


def test_formatter_handles_bad_percent_args() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "count %d", ("not-int",), None
    )
    out = BotLogFormatter().format(record)
    assert "count" in out
