# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Audit logs render their label/value fields as rich Field/Value tables."""

from __future__ import annotations

from datetime import UTC, datetime

from tcbot.modules.helper.messages import audit_logs
from tcbot.utils.time_and_date import utc_now


def _samples() -> dict[str, str]:
    """Build one message from every audit-log builder that posts to the log channel."""
    ts = utc_now()
    return {
        "ban": audit_logs.ban_log(1, "Ann", 2, "Bob", "spam", "ban-1", ts),
        "ban_update": audit_logs.ban_update_log(
            1, "Ann", 2, "Bob", 3, "Cid", "spam", "ban-1", ts
        ),
        "mute": audit_logs.mute_log(1, "Ann", 2, "Bob", "spam", "1h"),
        "unmute": audit_logs.unmute_log(1, "Ann", 2, "Bob"),
        "kick": audit_logs.kick_log(1, "Ann", 2, "Bob", "spam", -100, "Group"),
        "resetwarns": audit_logs.resetwarns_log(1, "Ann", 2, "Bob", 3, -100, "Group"),
        "warn": audit_logs.warn_log(1, "Ann", 2, "Bob", "spam", 2, 3, -100, "Group"),
        "unwarn": audit_logs.unwarn_log(1, "Ann", 2, "Bob", 1, 3, -100, "Group"),
        "unban": audit_logs.unban_log(1, "Ann", 2, "Bob", "ban-1", "appeal"),
        "appeal_received": audit_logs.appeal_received_log(
            1, "Ann", "ban-1", "https://t.me/c/1/2", ["rule 1"]
        ),
        "appeal_submitted": audit_logs.appeal_submitted_log(
            1, "Ann", "ban-1", "https://t.me/c/1/2"
        ),
        "appeal_approved": audit_logs.appeal_approved_edit(
            1, "Ann", 2, "Bob", "ban-1", "", ts
        ),
        "appeal_rejected": audit_logs.appeal_rejected_edit(
            1, "Ann", 2, "Bob", "ban-1", "", ts
        ),
        "appeal_unban": audit_logs.appeal_unban_log(1, "Ann", 2, "Bob", "ban-1"),
        "promoted": audit_logs.promoted(1, "Ann", "moderator", 2, "Bob"),
        "demoted": audit_logs.demoted(1, "Ann", "moderator", 2, "Bob"),
        "ownership": audit_logs.ownership_transferred(1, "Ann", 2, "Bob"),
        "promote_request": audit_logs.promote_request_log(1, "Ann", "ann", "req-1"),
        "promote_approved": audit_logs.promote_approved_log(
            1, "Ann", 2, "Bob", "req-1"
        ),
        "promote_rejected": audit_logs.promote_rejected_log(
            1, "Ann", 2, "Bob", "req-1"
        ),
        "group_connected": audit_logs.group_connected_log(
            -100, "Group", 2, "Bob", "group"
        ),
        "group_rejected": audit_logs.group_connection_rejected_log(
            -100, "Group", 2, "Bob"
        ),
        "group_disconnected": audit_logs.group_disconnected_log(
            -100, "Group", 2, "Bob"
        ),
        "group_bot_removed": audit_logs.group_bot_removed_log(-100, "Group"),
        "broadcast": audit_logs.broadcast_log(2, "Bob", "hello", 10, 1),
    }


def test_every_audit_log_groups_fields_into_a_rich_table() -> None:
    """Every log field lives in a two-column table, like the other panels."""
    for name, text in _samples().items():
        assert "<table bordered striped compact>" in text, name
        assert "<th>Field</th><th>Value</th>" in text, name
        assert "<ul>" not in text, name
        assert "\n<b>" not in text, name


def test_promoted_log_keeps_inline_markup_inside_the_table() -> None:
    """Mentions, code IDs, and the date stay usable inside table cells."""
    text = audit_logs.promoted(42, "tompearlgaming123", "moderator", 7, "Dizzy")

    assert "<td><b>User</b></td><td>tompearlgaming123</td>" in text
    assert "<td><b>User ID</b></td><td><code>42</code></td>" in text
    assert "<td><b>Role</b></td><td>Moderator</td>" in text
    assert "<td><b>Promoted by</b></td><td>Dizzy</td>" in text
    assert "<td><b>ID</b></td><td><code>7</code></td>" in text
    assert "<td><b>Date</b></td><td>" in text
    assert "<hr/>" in text


def test_date_and_time_are_separate_fields() -> None:
    """A log never joins the calendar date and clock time into one value."""
    text = audit_logs.ban_log(1, "Ann", 2, "Bob", "spam", "ban-1")
    assert "<td><b>Commit at</b></td><td>" in text
    assert "<td><b>Time</b></td><td>" in text
    assert " | " not in text


def test_proof_metadata_is_a_rich_table_below_the_slideshow() -> None:
    """Proof metadata is a Field/Value table with separate date and time rows."""
    ts = datetime(2026, 11, 22, 15, 27, tzinfo=UTC)
    caption = audit_logs.proof_caption_new(1, 2, "Bob", ts)
    assert caption.startswith("<table bordered striped compact>")
    assert "<td><b>Commit date</b></td><td>22-11-2026</td>" in caption
    assert "<td><b>Commit time</b></td><td>15:27</td>" in caption
    assert " | " not in caption
    assert "<figcaption>" not in caption


def test_untrusted_reason_stays_escaped_in_the_table() -> None:
    """A rich table does not weaken the escaping applied to user input."""
    text = audit_logs.ban_log(1, "Ann", 2, "Bob", "<script>x</script>", "ban-1")

    assert "&lt;script&gt;x&lt;/script&gt;" in text
    assert "<script>" not in text


def test_free_form_note_stays_outside_the_table() -> None:
    """The pending-review note is prose, not a label/value field."""
    text = audit_logs.appeal_received_log(1, "Ann", "ban-1", "")

    assert "<table bordered striped compact>" in text
    assert "<p>This appeal is pending review.</p>" in text
    assert "<ul>" not in text


def test_review_card_shows_the_appeal_text_when_the_forward_failed() -> None:
    """A failed forward must not leave reviewers with 'Appeal: N/A'."""
    text = audit_logs.appeal_received_log(
        1, "Ann", "ban-1", "", appeal_excerpt="please reconsider"
    )

    assert "Appeal text" in text
    assert "please reconsider" in text
    assert "N/A" not in text

    escaped = audit_logs.appeal_received_log(
        1, "Ann", "ban-1", "", appeal_excerpt="<script>x</script>"
    )
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
