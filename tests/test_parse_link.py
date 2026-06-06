# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.parse_link - pure URL builders."""

from __future__ import annotations

from tcbot.modules.helper.parse_link import (
    appeal_deep_link,
    chat_id_to_link_id,
    message_link,
)

# ──────────────────────── chat_id_to_link_id ────────────────────── #


def test_strips_minus_100_prefix_for_supergroup() -> None:
    assert chat_id_to_link_id(-1001234567890) == "1234567890"


def test_strips_plain_negative_prefix_for_non_supergroup() -> None:
    assert chat_id_to_link_id(-1234567890) == "1234567890"


def test_positive_chat_id_returned_unchanged() -> None:
    assert chat_id_to_link_id(999) == "999"


def test_exactly_minus_100_prefix_stripped_correctly() -> None:
    result = chat_id_to_link_id(-1001000000001)
    assert result == "1000000001"


def test_short_negative_id_has_leading_dash_stripped() -> None:
    result = chat_id_to_link_id(-100)
    assert result == ""


def test_non_minus100_negative_strips_minus_sign() -> None:
    assert chat_id_to_link_id(-500) == "500"


# ────────────────────────── message_link ────────────────────────── #


def test_message_link_without_thread() -> None:
    link = message_link(-1001234567890, 42)
    assert link == "https://t.me/c/1234567890/42"


def test_message_link_with_thread() -> None:
    link = message_link(-1001234567890, 42, thread_id=7)
    assert link == "https://t.me/c/1234567890/42?thread=7"


def test_message_link_thread_none_omits_query() -> None:
    link = message_link(-1001234567890, 1, thread_id=None)
    assert "thread" not in link


def test_message_link_thread_zero_treated_as_falsy() -> None:
    link = message_link(-1001234567890, 1, thread_id=0)
    assert "thread" not in link


def test_message_link_uses_tme_c_scheme() -> None:
    link = message_link(-1001000000001, 99)
    assert link.startswith("https://t.me/c/")


# ────────────────────────── appeal_deep_link ────────────────────── #


def test_appeal_deep_link_format() -> None:
    link = appeal_deep_link("mybot", "abc123")
    assert link == "https://t.me/mybot?start=appeal_abc123"


def test_appeal_deep_link_contains_ban_id() -> None:
    ban_id = "deadbeef"
    link = appeal_deep_link("tcfedbot", ban_id)
    assert ban_id in link


def test_appeal_deep_link_contains_bot_username() -> None:
    link = appeal_deep_link("myfedbot", "xyz")
    assert "myfedbot" in link


def test_appeal_deep_link_starts_with_https() -> None:
    link = appeal_deep_link("bot", "id")
    assert link.startswith("https://t.me/")
