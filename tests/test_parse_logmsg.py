# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.parse_logmsg.LogBuilder - fluent log builder."""

from __future__ import annotations

from tcbot.modules.helper.parse_logmsg import LogBuilder

# ───────────────────────── LogBuilder core ──────────────────────── #


def test_build_returns_string() -> None:
    result = LogBuilder("Title").build()
    assert isinstance(result, str)


def test_title_appears_first_line() -> None:
    result = LogBuilder("My Title").build()
    assert result.startswith("My Title")


def test_str_equals_build() -> None:
    lb = LogBuilder("T")
    assert str(lb) == lb.build()


def test_field_appends_label_colon_value() -> None:
    result = LogBuilder("T").field("Reason", "spam").build()
    assert "Reason: spam" in result


def test_field_escapes_html_by_default() -> None:
    result = LogBuilder("T").field("Note", "<script>").build()
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_field_escape_false_keeps_raw_markup() -> None:
    result = LogBuilder("T").field("Link", "<b>bold</b>", escape=False).build()
    assert "<b>bold</b>" in result


def test_code_field_wraps_value_in_code_tag() -> None:
    result = LogBuilder("T").code_field("ID", "12345").build()
    assert "<code>12345</code>" in result


def test_mention_field_contains_user_id() -> None:
    result = LogBuilder("T").mention_field("User", 99999, "Alice").build()
    assert "99999" in result


def test_mention_field_contains_name() -> None:
    result = LogBuilder("T").mention_field("User", 1, "Alice").build()
    assert "Alice" in result


def test_link_field_contains_url() -> None:
    result = LogBuilder("T").link_field("Proof", "View", "https://t.me/c/1/2").build()
    assert "https://t.me/c/1/2" in result


def test_link_field_contains_text() -> None:
    result = LogBuilder("T").link_field("Label", "ClickHere", "https://x.com").build()
    assert "ClickHere" in result


def test_raw_appends_text_without_escaping() -> None:
    result = LogBuilder("T").raw("<b>Bold</b>").build()
    assert "<b>Bold</b>" in result


def test_section_inserts_blank_line() -> None:
    result = LogBuilder("T").field("A", "1").section().field("B", "2").build()
    assert "\n\n" in result


def test_user_block_contains_user_id() -> None:
    result = LogBuilder("T").user_block(12345, "Bob").build()
    assert "12345" in result


def test_user_block_contains_name() -> None:
    result = LogBuilder("T").user_block(1, "Bob").build()
    assert "Bob" in result


def test_actor_block_contains_actor_id() -> None:
    result = LogBuilder("T").actor_block(67890, "Admin").build()
    assert "67890" in result


def test_actor_block_uses_default_admin_label() -> None:
    result = LogBuilder("T").actor_block(1, "Charlie").build()
    assert "Admin:" in result


def test_fluent_chain_returns_same_instance() -> None:
    lb = LogBuilder("T")
    returned = lb.field("X", "y")
    assert returned is lb


def test_date_field_appends_date_line() -> None:
    from datetime import datetime, timezone

    ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = LogBuilder("T").date(ts, label="Commit at").build()
    assert "Commit at:" in result
    assert "2025" in result or "01" in result


def test_multiple_fields_all_present() -> None:
    result = (
        LogBuilder("Title")
        .field("A", "alpha")
        .field("B", "beta")
        .field("C", "gamma")
        .build()
    )
    assert "A: alpha" in result
    assert "B: beta" in result
    assert "C: gamma" in result


# ─────────────────── proof_caption_update ───────────────────────── #


def test_proof_caption_update_contains_target_id() -> None:
    """Target ID must appear in the caption."""
    from datetime import datetime, timezone

    from tcbot.modules.helper.parse_logmsg import proof_caption_update

    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = proof_caption_update(12345, 67890, "Admin", ts)
    assert "12345" in result


def test_proof_caption_update_contains_admin_name() -> None:
    """Admin name must appear in the caption."""
    from datetime import datetime, timezone

    from tcbot.modules.helper.parse_logmsg import proof_caption_update

    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = proof_caption_update(1, 2, "SomeAdmin", ts)
    assert "SomeAdmin" in result


def test_proof_caption_update_with_prev_link_includes_previous_section() -> None:
    """When prev_proof_lnk is provided the caption must contain 'Previous' and the URL."""
    from datetime import datetime, timezone

    from tcbot.modules.helper.parse_logmsg import proof_caption_update

    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = proof_caption_update(
        1, 2, "Admin", ts, prev_proof_lnk="https://t.me/c/1/2"
    )
    assert "Previous" in result
    assert "https://t.me/c/1/2" in result


def test_proof_caption_update_without_prev_link_omits_previous_section() -> None:
    """When prev_proof_lnk is None the 'Previous' section must not appear."""
    from datetime import datetime, timezone

    from tcbot.modules.helper.parse_logmsg import proof_caption_update

    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = proof_caption_update(1, 2, "Admin", ts)
    assert "Previous" not in result


# ─────────────────── promote_approved_log ───────────────────────── #


def test_promote_approved_log_contains_request_id() -> None:
    """Promotion approval log must include the request ID."""
    from tcbot.modules.helper.parse_logmsg import promote_approved_log

    result = promote_approved_log(1, "Alice", 2, "Bob", "req-abc-123")
    assert "req-abc-123" in result


def test_promote_approved_log_contains_target_name() -> None:
    """Promotion approval log must include the promoted user's name."""
    from tcbot.modules.helper.parse_logmsg import promote_approved_log

    result = promote_approved_log(1, "Alice", 2, "Bob", "req-001")
    assert "Alice" in result


# ─────────────────── promote_rejected_log ───────────────────────── #


def test_promote_rejected_log_contains_request_id() -> None:
    """Promotion rejection log must include the request ID."""
    from tcbot.modules.helper.parse_logmsg import promote_rejected_log

    result = promote_rejected_log(1, "Alice", 2, "Bob", "req-xyz-456")
    assert "req-xyz-456" in result


def test_promote_rejected_log_contains_target_and_actor() -> None:
    """Promotion rejection log must include both the rejected user and the actor."""
    from tcbot.modules.helper.parse_logmsg import promote_rejected_log

    result = promote_rejected_log(1, "Alice", 2, "Moderator", "req-002")
    assert "Alice" in result
    assert "Moderator" in result


# ─────────────────── group_disconnected_log ─────────────────────── #


def test_group_disconnected_log_contains_chat_title() -> None:
    """Group-disconnected log must contain the group title."""
    from tcbot.modules.helper.parse_logmsg import group_disconnected_log

    result = group_disconnected_log(-1001234567890, "My Group", 99, "Moderator")
    assert "My Group" in result


def test_group_disconnected_log_contains_actor_name() -> None:
    """Group-disconnected log must contain the actor's name."""
    from tcbot.modules.helper.parse_logmsg import group_disconnected_log

    result = group_disconnected_log(-1001234567890, "My Group", 99, "Moderator")
    assert "Moderator" in result


# ─────────────────── group_bot_removed_log ──────────────────────── #


def test_group_bot_removed_log_contains_chat_title() -> None:
    """Bot-removed log must contain the group title."""
    from tcbot.modules.helper.parse_logmsg import group_bot_removed_log

    result = group_bot_removed_log(-1001234567890, "Test Group")
    assert "Test Group" in result


def test_group_bot_removed_log_is_string() -> None:
    """Bot-removed log must return a non-empty string."""
    from tcbot.modules.helper.parse_logmsg import group_bot_removed_log

    result = group_bot_removed_log(-1001000000001, "Some Group")
    assert isinstance(result, str)
    assert result.strip()
