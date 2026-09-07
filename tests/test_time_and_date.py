# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central clock helpers: UTC normalization and display formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from tcbot.utils.time_and_date import (
    elapsed_ms,
    fmt_dt,
    from_timestamp,
    monotonic,
    to_utc,
)


def test_to_utc_assumes_naive_is_utc() -> None:
    assert to_utc(datetime(2026, 1, 2, 3, 4)) == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_to_utc_converts_aware() -> None:
    shifted = datetime(2026, 1, 2, 5, 4, tzinfo=timezone(timedelta(hours=2)))
    assert to_utc(shifted) == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_fmt_dt_renders_expected_shape() -> None:
    assert fmt_dt(datetime(2026, 1, 2, 3, 4, tzinfo=UTC)) == "02-01-2026 | 03:04"
    assert fmt_dt(datetime(2026, 1, 2, 3, 4)) == "02-01-2026 | 03:04"


def test_from_timestamp_epoch() -> None:
    assert from_timestamp(0) == datetime(1970, 1, 1, tzinfo=UTC)


def test_monotonic_elapsed_non_negative() -> None:
    assert elapsed_ms(monotonic()) >= 0
