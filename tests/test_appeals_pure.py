# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Pure-function tests for tcbot.modules.appeals.
"""

from __future__ import annotations

from datetime import timedelta

from tcbot import cfg
from tcbot.modules import appeals
from tcbot.utils.timedate_format import utc_now

# ── Imports and test setup ─────────────────────────────────────────────────


def test_starts_with_appeal_tag_lowercase() -> None:
    assert appeals.starts_with_appeal_tag("#appeal\nLog link: ...")


def test_starts_with_appeal_tag_uppercase() -> None:
    assert appeals.starts_with_appeal_tag("#APPEAL body")


def test_starts_with_appeal_tag_mixed_case() -> None:
    assert appeals.starts_with_appeal_tag("   #Appeal stuff")


def test_starts_with_appeal_tag_rejects_no_hash() -> None:
    assert not appeals.starts_with_appeal_tag("Hello, I want to appeal")


def test_starts_with_appeal_tag_rejects_empty() -> None:
    assert not appeals.starts_with_appeal_tag("")


def test_starts_with_appeal_tag_rejects_hash_after_text() -> None:
    assert not appeals.starts_with_appeal_tag("appeal #123")


def test_text_references_log_message_matches_standalone_id() -> None:
    text = "Log link: https://t.me/c/12345/67?thread=10"
    assert appeals.text_references_log_message(text, 67)


def test_text_references_log_message_rejects_partial_match() -> None:
    text = "Log link: https://t.me/c/12345/67?thread=10"
    assert not appeals.text_references_log_message(text, 670)
    assert not appeals.text_references_log_message(text, 6)


def test_text_references_log_message_matches_bare_number() -> None:
    assert appeals.text_references_log_message("see /67.", 67)


def test_reviewer_locked_out_blocks_other_admin_within_window() -> None:
    ts = utc_now() - timedelta(hours=1)
    assert appeals.reviewer_locked_out(
        review_timestamp=ts,
        ban_admin_id=10,
        reviewer_id=20,
    )


def test_reviewer_locked_out_allows_banning_admin() -> None:
    ts = utc_now() - timedelta(hours=1)
    assert not appeals.reviewer_locked_out(
        review_timestamp=ts,
        ban_admin_id=10,
        reviewer_id=10,
    )


def test_reviewer_locked_out_allows_anyone_after_12h() -> None:
    ts = utc_now() - timedelta(hours=13)
    assert not appeals.reviewer_locked_out(
        review_timestamp=ts,
        ban_admin_id=10,
        reviewer_id=20,
    )


def test_reviewer_locked_out_returns_false_when_timestamp_none() -> None:
    assert not appeals.reviewer_locked_out(
        review_timestamp=None,
        ban_admin_id=10,
        reviewer_id=20,
    )


def test_reviewer_locked_out_returns_false_when_ban_admin_none() -> None:
    assert not appeals.reviewer_locked_out(
        review_timestamp=utc_now(),
        ban_admin_id=None,
        reviewer_id=20,
    )


def test_module_level_appeal_uses_configured_log_handle() -> None:
    assert appeals.appeal.log_channel == cfg.appeal_log_handle
