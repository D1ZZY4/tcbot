# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Tests for :mod:`tgbot_tcf.modules.log_templates`.

Every channel log message must:

* Begin with a bold title line.
* Include the exact :data:`Messages.BRANDING_LINE` immediately below the title.
"""
from __future__ import annotations

from datetime import datetime

from tgbot_tcf.modules import log_templates
from tgbot_tcf.modules.messages import M


def _assert_branding_present(text: str) -> None:
    assert M.BRANDING_LINE in text
    title_line, branding_line, *_ = text.splitlines()
    assert title_line.startswith("<b>") and title_line.endswith("</b>")
    assert branding_line == M.BRANDING_LINE


def test_new_affiliated_group_layout() -> None:
    out = log_templates.new_affiliated_group(
        title="Infinix Indonesia",
        chat_id=-1001234567890,
        owner_id=42,
        owner_name="Budi",
    )
    _assert_branding_present(out)
    assert "Infinix Indonesia" in out
    assert "(ID: -1001234567890)" in out
    assert "Budi" in out


def test_new_ban_includes_admin_target_and_reason() -> None:
    when = datetime(2026, 4, 30, 12, 30)
    out = log_templates.new_ban(
        admin_id=1,
        admin_name="Andi",
        target_id=2,
        target_name="Citra",
        reason="Spamming links",
        timestamp=when,
    )
    _assert_branding_present(out)
    assert "Spamming links" in out
    assert "Commit at: 30-04-2026 | 12:30" in out
    assert "Andi" in out and "Citra" in out


def test_unban_with_and_without_reason() -> None:
    base_kwargs = dict(
        admin_id=1, admin_name="Andi", target_id=2, target_name="Citra"
    )
    out_no_reason = log_templates.unban(**base_kwargs)
    assert "Unban Reason:" not in out_no_reason
    out_with_reason = log_templates.unban(**base_kwargs, reason="Appeal Approved")
    assert "Unban Reason: Appeal Approved" in out_with_reason


def test_enforcement_summary_format() -> None:
    out = log_templates.enforcement_summary(success=10, failure=2, action="Enforced")
    assert out == "\n\nEnforced in 10 group(s); failed in 2 group(s)."


def test_admin_promoted_and_demoted_show_actor_and_target() -> None:
    promo = log_templates.admin_promoted(
        target_id=2,
        target_name="Citra",
        promoted_by_id=1,
        promoted_by_name="Andi",
    )
    _assert_branding_present(promo)
    assert "ID: 2" in promo and "ID: 1" in promo

    demo = log_templates.admin_demoted(
        target_id=2,
        target_name="Citra",
        demoted_by_id=1,
        demoted_by_name="Andi",
    )
    _assert_branding_present(demo)
    assert "Citra" in demo and "Andi" in demo


def test_ownership_transfer_layout() -> None:
    out = log_templates.ownership_transferred(
        new_owner_id=2,
        new_owner_name="Citra",
        old_owner_id=1,
        old_owner_name="Andi",
    )
    _assert_branding_present(out)
    assert "New Owner" in out and "Previous Owner" in out


def test_appeal_submitted_includes_link_and_ban_id() -> None:
    when = datetime(2026, 4, 30, 12, 30)
    out = log_templates.appeal_submitted(
        user_id=2,
        user_name="Citra",
        ban_id="2_1714492200",
        appeal_link="https://t.me/c/1234/56?thread=12",
        submitted_at=when,
    )
    _assert_branding_present(out)
    assert "2_1714492200" in out
    assert 'href="https://t.me/c/1234/56?thread=12"' in out


def test_proof_caption_new_includes_admin_and_timestamp() -> None:
    out = log_templates.proof_caption_new(
        target_id=2,
        admin_id=1,
        admin_name="Andi",
        timestamp=datetime(2026, 4, 30, 12, 30),
    )
    assert "ID: 2" in out
    assert "Admin ID: 1" in out
    assert "Commit at: 30-04-2026 | 12:30" in out


def test_broadcast_log_truncates_long_text() -> None:
    long_text = "x" * 500
    out = log_templates.broadcast_log(
        admin_id=1, admin_name="Andi", text=long_text, success=10, failure=1
    )
    _assert_branding_present(out)
    # Only the first 100 characters should be embedded.
    assert "x" * 100 in out
    assert "x" * 101 not in out
