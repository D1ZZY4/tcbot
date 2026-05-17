# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Unit tests for parse_link helpers and timedate_format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.modules.helper.parse_link import (
    chat_id_to_link_id,
    message_link,
    safe_first_name,
    topic_link,
    user_link,
    utcnow,
)
from tcbot.utils.timedate_format import fmt_dt, utc_now, utc_now_str


## ── utcnow / utc_now ──────────────────────────────────────────────────

def test_utcnow_returns_naive_datetime() -> None:
    now = utcnow()
    assert now.tzinfo is None


def test_utcnow_is_close_to_real_time() -> None:
    now = utcnow()
    wall = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((wall - now).total_seconds()) < 5


def test_utc_now_returns_aware_datetime() -> None:
    now = utc_now()
    assert now.tzinfo is not None


## ── fmt_dt ────────────────────────────────────────────────────────────

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


## ── chat_id_to_link_id ─────────────────────────────────────────────────

def test_chat_id_to_link_id_strips_supergroup_prefix() -> None:
    assert chat_id_to_link_id(-1001234567890) == "1234567890"


def test_chat_id_to_link_id_strips_negative_sign_for_short_id() -> None:
    result = chat_id_to_link_id(-2002)
    assert result == "2002"


def test_chat_id_to_link_id_with_plain_channel() -> None:
    assert chat_id_to_link_id(-1009999999999) == "9999999999"


## ── message_link / topic_link ───────────────────────────────────────────

def test_message_link_without_thread() -> None:
    url = message_link(-1001111111111, 42)
    assert url == "https://t.me/c/1111111111/42"


def test_message_link_with_thread() -> None:
    url = message_link(-1001111111111, 42, thread_id=7)
    assert url == "https://t.me/c/1111111111/42?thread=7"


def test_topic_link_delegates_to_message_link() -> None:
    assert topic_link(-1001111111111, 42, 7) == "https://t.me/c/1111111111/42?thread=7"


## ── user_link ───────────────────────────────────────────────────────────

def test_user_link_escapes_html_in_name() -> None:
    result = user_link(123, "<b>Evil</b>")
    assert '<a href="tg://user?id=123">' in result
    assert "&lt;b&gt;Evil&lt;/b&gt;" in result
    assert "<b>Evil</b>" not in result


def test_user_link_falls_back_to_id_when_name_blank() -> None:
    assert "456" in user_link(456, "")


## ── safe_first_name ──────────────────────────────────────────────────────

def test_safe_first_name_prefers_first_name() -> None:
    obj = SimpleNamespace(first_name="Andi", title="Group", id=99)
    assert safe_first_name(obj) == "Andi"


def test_safe_first_name_falls_back_to_title() -> None:
    obj = SimpleNamespace(first_name=None, title="Group", id=99)
    assert safe_first_name(obj) == "Group"


def test_safe_first_name_falls_back_to_id() -> None:
    obj = SimpleNamespace(first_name=None, title=None, id=99)
    assert safe_first_name(obj) == "99"


def test_safe_first_name_returns_unknown_for_bare_object() -> None:
    assert safe_first_name(SimpleNamespace()) == "Unknown"
