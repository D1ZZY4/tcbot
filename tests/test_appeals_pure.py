# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Pure-function tests for :mod:`tgbot_tcf.modules.appeals`."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from tgbot_tcf.modules import appeals
from tgbot_tcf.utils.format import utcnow


def test_starts_with_appeal_tag_accepts_uppercase_and_whitespace() -> None:
    assert appeals.starts_with_appeal_tag("#appeal\nLog link: ...")
    assert appeals.starts_with_appeal_tag("   #APPEAL body")
    assert appeals.starts_with_appeal_tag("#Appeal stuff")


def test_starts_with_appeal_tag_rejects_other_text() -> None:
    assert not appeals.starts_with_appeal_tag("Hello, I want to appeal")
    assert not appeals.starts_with_appeal_tag("")
    assert not appeals.starts_with_appeal_tag("appeal #123")


def test_text_references_log_message_matches_url_path() -> None:
    text = "Log link: https://t.me/c/12345/67?thread=10"
    assert appeals.text_references_log_message(text, 67)
    assert not appeals.text_references_log_message(text, 670)
    assert not appeals.text_references_log_message(text, 6)


def test_text_references_log_message_handles_trailing_punctuation() -> None:
    text = "see /67."
    assert appeals.text_references_log_message(text, 67)


def test_reviewer_locked_out_blocks_other_admin_in_window() -> None:
    review_ts = utcnow() - timedelta(hours=1)
    assert appeals.reviewer_locked_out(
        review_timestamp=review_ts,
        ban_admin_id=10,
        reviewer_id=20,
    )


def test_reviewer_locked_out_allows_original_admin() -> None:
    review_ts = utcnow() - timedelta(hours=1)
    assert not appeals.reviewer_locked_out(
        review_timestamp=review_ts,
        ban_admin_id=10,
        reviewer_id=10,
    )


def test_reviewer_locked_out_allows_anyone_after_window() -> None:
    review_ts = utcnow() - timedelta(hours=13)
    assert not appeals.reviewer_locked_out(
        review_timestamp=review_ts,
        ban_admin_id=10,
        reviewer_id=20,
    )


def test_reviewer_locked_out_handles_missing_metadata() -> None:
    assert not appeals.reviewer_locked_out(
        review_timestamp=None, ban_admin_id=10, reviewer_id=20
    )
    assert not appeals.reviewer_locked_out(
        review_timestamp=utcnow(), ban_admin_id=None, reviewer_id=20
    )


def test_now_returns_current_utc() -> None:
    sentinel = utcnow()
    with patch("tgbot_tcf.modules.appeals.utcnow", return_value=sentinel):
        assert appeals.now() is sentinel
