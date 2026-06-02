# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.utils.timedate_format."""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.utils.timedate_format import fmt_dt, to_utc, utc_now, utc_now_str


class TestUtcNow:
    def test_returns_datetime(self):
        result = utc_now()
        assert isinstance(result, datetime)

    def test_is_tz_aware(self):
        result = utc_now()
        assert result.tzinfo is not None

    def test_is_utc(self):
        result = utc_now()
        assert result.tzinfo == timezone.utc


class TestToUtc:
    def test_naive_datetime_assumed_utc(self):
        naive = datetime(2024, 6, 1, 12, 0, 0)
        result = to_utc(naive)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024
        assert result.hour == 12

    def test_aware_utc_unchanged(self):
        aware = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = to_utc(aware)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_preserves_microseconds(self):
        naive = datetime(2024, 1, 15, 8, 30, 45, 123456)
        result = to_utc(naive)
        assert result.microsecond == 123456

    def test_aware_non_utc_converted(self):
        from datetime import timedelta

        plus2 = timezone(timedelta(hours=2))
        aware_plus2 = datetime(2024, 6, 1, 14, 0, 0, tzinfo=plus2)
        result = to_utc(aware_plus2)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12


class TestFmtDt:
    def test_format_aware(self):
        dt = datetime(2024, 6, 1, 8, 5, 0, tzinfo=timezone.utc)
        assert fmt_dt(dt) == "01-06-2024 | 08:05"

    def test_format_naive_assumed_utc(self):
        dt = datetime(2024, 12, 31, 23, 59, 0)
        assert fmt_dt(dt) == "31-12-2024 | 23:59"

    def test_zero_padded_day_month(self):
        dt = datetime(2024, 1, 5, 3, 7, 0, tzinfo=timezone.utc)
        assert fmt_dt(dt) == "05-01-2024 | 03:07"

    def test_returns_string(self):
        dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert isinstance(fmt_dt(dt), str)

    def test_separator_format(self):
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = fmt_dt(dt)
        assert " | " in result


class TestUtcNowStr:
    def test_returns_string(self):
        assert isinstance(utc_now_str(), str)

    def test_matches_fmt_dt_pattern(self):
        result = utc_now_str()
        assert " | " in result
        parts = result.split(" | ")
        assert len(parts) == 2
        date_part, time_part = parts
        assert len(date_part) == 10
        assert len(time_part) == 5

    def test_date_part_format(self):
        result = utc_now_str()
        date_part = result.split(" | ")[0]
        day, month, year = date_part.split("-")
        assert len(day) == 2
        assert len(month) == 2
        assert len(year) == 4
