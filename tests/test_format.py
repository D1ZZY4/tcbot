# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Unit tests for parse_link helpers and timedate_format."""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.modules.helper.parse_link import (
    chat_id_to_link_id,
    message_link,
)
from tcbot.utils.timedate_format import fmt_dt, to_utc, utc_now, utc_now_str

# ───────────────────────────── utc_now ──────────────────────────── #


def test_utc_now_returns_aware_datetime() -> None:
    now = utc_now()
    assert now.tzinfo is not None


def test_to_utc_handles_naive_and_aware() -> None:
    naive = datetime(2026, 1, 1, 12, 0)
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert to_utc(naive).tzinfo is not None
    assert to_utc(aware).tzinfo is not None


# ───────────────────────────── fmt_dt ───────────────────────────── #


def test_fmt_dt_formats_as_dd_mm_yyyy_pipe_hhmm() -> None:
    dt = datetime(2026, 4, 30, 14, 5, tzinfo=timezone.utc)
    assert fmt_dt(dt) == "30-04-2026 | 14:05"


def test_fmt_dt_handles_naive_datetime() -> None:
    dt = datetime(2026, 1, 1, 0, 0)
    result = fmt_dt(dt)
    assert result == "01-01-2026 | 00:00"


def test_utc_now_str_matches_pattern() -> None:
    out = utc_now_str()
    assert out[2] == "-" and out[5] == "-" and out[10:13] == " | "


# ─────────────────────── chat_id_to_link_id ─────────────────────── #


def test_chat_id_to_link_id_strips_supergroup_prefix() -> None:
    assert chat_id_to_link_id(-1001234567890) == "1234567890"


def test_chat_id_to_link_id_strips_negative_sign_for_short_id() -> None:
    result = chat_id_to_link_id(-2002)
    assert result == "2002"


def test_chat_id_to_link_id_with_plain_channel() -> None:
    assert chat_id_to_link_id(-1009999999999) == "9999999999"


# ─────────────────────────── message_link ───────────────────────── #


def test_message_link_without_thread() -> None:
    url = message_link(-1001111111111, 42)
    assert url == "https://t.me/c/1111111111/42"


def test_message_link_with_thread() -> None:
    url = message_link(-1001111111111, 42, thread_id=7)
    assert url == "https://t.me/c/1111111111/42?thread=7"
