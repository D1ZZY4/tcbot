# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central clock helpers: UTC normalization and display formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from tcbot.utils.time_and_date import (
    elapsed_ms,
    fmt_date,
    fmt_duration,
    fmt_time,
    monotonic,
    parse_duration,
    to_utc,
)


def test_to_utc_assumes_naive_is_utc() -> None:
    assert to_utc(datetime(2026, 1, 2, 3, 4)) == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_to_utc_converts_aware() -> None:
    shifted = datetime(2026, 1, 2, 5, 4, tzinfo=timezone(timedelta(hours=2)))
    assert to_utc(shifted) == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_fmt_date_and_fmt_time_are_separate() -> None:
    """Date and time are independent: neither leaks the other's separator."""
    value = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    assert fmt_date(value) == "02-01-2026"
    assert fmt_time(value) == "03:04"
    assert "|" not in fmt_date(value)
    assert "-" not in fmt_time(value)


def test_fmt_date_and_time_convert_another_offset_to_utc() -> None:
    shifted = datetime(2026, 1, 2, 5, 4, tzinfo=timezone(timedelta(hours=2)))
    assert fmt_date(shifted) == "02-01-2026"
    assert fmt_time(shifted) == "03:04"


def test_monotonic_elapsed_non_negative() -> None:
    assert elapsed_ms(monotonic()) >= 0


def test_fmt_duration_permanent_and_tiers() -> None:
    assert fmt_duration(None) == "permanently"
    assert fmt_duration(timedelta(seconds=30)) == "30s"
    assert fmt_duration(timedelta(minutes=5)) == "5m"
    assert fmt_duration(timedelta(hours=3)) == "3h"
    assert fmt_duration(timedelta(days=2)) == "2d"
    assert fmt_duration(timedelta(days=14)) == "2w"
    assert fmt_duration(timedelta(days=60)) == "2mo"
    assert fmt_duration(timedelta(days=800)) == "2ye"


def test_parse_duration_round_trip() -> None:
    assert parse_duration("90s") == timedelta(seconds=90)
    assert parse_duration("3d") == timedelta(days=3)
    assert parse_duration("nope") is None


def test_parse_duration_accepts_every_unit_inside_the_cap() -> None:
    """A long token stays valid when its own unit fits the documented cap.

    Building every unit eagerly made the year conversion overflow and
    returned None for a second-based token that was still inside the cap,
    so a moderator saw a valid duration rejected.
    """
    assert parse_duration("1000000s") == timedelta(seconds=1_000_000)
    assert parse_duration("366d") == timedelta(days=366)


def test_parse_duration_rejects_tokens_past_the_cap() -> None:
    """Telegram turns restrictions beyond 366 days into permanent ones."""
    assert parse_duration("367d") is None
    assert parse_duration("2ye") is None
    assert parse_duration("999999999999999ye") is None


def test_parse_duration_rejects_an_overlong_digit_run() -> None:
    """A token past Python's int conversion cap is invalid, not fatal."""
    assert parse_duration("9" * 5000 + "d") is None
