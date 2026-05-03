# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Unit tests for :mod:`tcbot.modules.helper.parse_link` formatters."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.modules.helper.parse_link import (
    chat_id_to_link_id,
    safe_first_name,
    topic_link,
    user_link,
    utcnow,
)
from tcbot.utils.timedate_format import fmt_dt, utc_now_str as fmt_now


def test_utcnow_is_naive_utc() -> None:
    now = utcnow()
    assert now.tzinfo is None
    delta = abs(
        (now - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
    )
    assert delta < 5


def test_fmt_dt_uses_dd_mm_yyyy_pipe_hh_mm() -> None:
    dt = datetime(2026, 4, 30, 14, 5)
    assert fmt_dt(dt) == "30-04-2026 | 14:05"


def test_fmt_now_matches_pattern() -> None:
    out = fmt_now()
    assert len(out) == len("DD-MM-YYYY | HH:MM")
    assert out[2] == "-" and out[5] == "-" and out[10:13] == " | "


def test_user_link_escapes_html() -> None:
    link = user_link(123, "<b>Evil</b>")
    assert link.startswith('<a href="tg://user?id=123">')
    assert "&lt;b&gt;Evil&lt;/b&gt;" in link
    assert "<b>Evil</b>" not in link


def test_user_link_falls_back_to_id_when_name_blank() -> None:
    assert "456" in user_link(456, "")


def test_chat_id_to_link_id_strips_supergroup_prefix() -> None:
    assert chat_id_to_link_id(-1001234567890) == "1234567890"


def test_chat_id_to_link_id_keeps_short_ids() -> None:
    assert chat_id_to_link_id(-2002) == "2002"


def test_topic_link_uses_thread_query() -> None:
    link = topic_link(-1001111111111, 42, 7)
    assert link == "https://t.me/c/1111111111/42?thread=7"


def test_safe_first_name_prefers_first_name() -> None:
    obj = SimpleNamespace(first_name="Andi", title=None, id=99)
    assert safe_first_name(obj) == "Andi"


def test_safe_first_name_falls_back_to_title() -> None:
    obj = SimpleNamespace(first_name=None, title="Group", id=99)
    assert safe_first_name(obj) == "Group"


def test_safe_first_name_falls_back_to_id() -> None:
    obj = SimpleNamespace(first_name=None, title=None, id=99)
    assert safe_first_name(obj) == "99"


def test_safe_first_name_handles_missing_attrs() -> None:
    assert safe_first_name(SimpleNamespace()) == "Unknown"
