# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.utils.pagination."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import InlineKeyboardButton

from tcbot.utils.pagination import date_or_unknown, nav_row, paginate


class TestPaginateEmpty:
    def test_empty_list_returns_single_page(self):
        chunk, total_pages, page = paginate([], 0, 5)
        assert chunk == []
        assert total_pages == 1
        assert page == 0

    def test_empty_list_any_page_still_one_page(self):
        _, total_pages, clamped = paginate([], 99, 5)
        assert total_pages == 1
        assert clamped == 0


class TestPaginateSlicing:
    def test_first_page(self):
        items = list(range(10))
        chunk, total_pages, page = paginate(items, 0, 3)
        assert chunk == [0, 1, 2]
        assert total_pages == 4
        assert page == 0

    def test_second_page(self):
        items = list(range(10))
        chunk, _, page = paginate(items, 1, 3)
        assert chunk == [3, 4, 5]
        assert page == 1

    def test_last_page_partial(self):
        items = list(range(10))
        chunk, total_pages, page = paginate(items, 3, 3)
        assert chunk == [9]
        assert total_pages == 4
        assert page == 3

    def test_exact_fit(self):
        items = list(range(6))
        chunk, total_pages, _ = paginate(items, 1, 3)
        assert chunk == [3, 4, 5]
        assert total_pages == 2

    def test_single_item(self):
        chunk, total_pages, page = paginate(["only"], 0, 5)
        assert chunk == ["only"]
        assert total_pages == 1
        assert page == 0

    def test_page_size_one(self):
        items = [10, 20, 30]
        chunk, total_pages, page = paginate(items, 2, 1)
        assert chunk == [30]
        assert total_pages == 3
        assert page == 2


class TestPaginateClamping:
    def test_negative_page_clamped_to_zero(self):
        items = list(range(5))
        chunk, _, page = paginate(items, -1, 3)
        assert page == 0
        assert chunk == [0, 1, 2]

    def test_page_beyond_end_clamped(self):
        items = list(range(5))
        chunk, total_pages, page = paginate(items, 99, 3)
        assert page == total_pages - 1
        assert chunk == [3, 4]


class TestNavRow:
    def test_single_page_no_buttons(self):
        row = nav_row(0, 1, "prefix")
        assert row == []

    def test_first_page_next_only(self):
        row = nav_row(0, 3, "prefix")
        assert len(row) == 1
        assert row[0].text == "Next »"
        assert row[0].callback_data == "prefix:1"

    def test_last_page_prev_only(self):
        row = nav_row(2, 3, "prefix")
        assert len(row) == 1
        assert row[0].text == "« Prev"
        assert row[0].callback_data == "prefix:1"

    def test_middle_page_both_buttons(self):
        row = nav_row(1, 3, "prefix")
        assert len(row) == 2
        assert row[0].text == "« Prev"
        assert row[0].callback_data == "prefix:0"
        assert row[1].text == "Next »"
        assert row[1].callback_data == "prefix:2"

    def test_callback_data_format(self):
        row = nav_row(0, 2, "check_bans:123")
        assert row[0].callback_data == "check_bans:123:1"

    def test_returns_list_of_inline_keyboard_buttons(self):
        row = nav_row(0, 2, "cb")
        assert all(isinstance(b, InlineKeyboardButton) for b in row)

    def test_two_pages_first_page(self):
        row = nav_row(0, 2, "p")
        assert len(row) == 1
        assert row[0].text == "Next »"

    def test_two_pages_second_page(self):
        row = nav_row(1, 2, "p")
        assert len(row) == 1
        assert row[0].text == "« Prev"


class TestDateOrUnknown:
    def test_none_returns_unknown(self):
        assert date_or_unknown(None) == "Unknown"

    def test_falsy_zero_returns_unknown(self):
        assert date_or_unknown(0) == "Unknown"

    def test_empty_string_returns_unknown(self):
        assert date_or_unknown("") == "Unknown"

    def test_datetime_returns_formatted(self):
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = date_or_unknown(dt)
        assert result == "01-06-2024 | 12:00"

    def test_naive_datetime_handled(self):
        dt = datetime(2024, 1, 15, 8, 30, 0)
        result = date_or_unknown(dt)
        assert "15-01-2024" in result

    def test_returns_string(self):
        assert isinstance(date_or_unknown(None), str)
        dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert isinstance(date_or_unknown(dt), str)
