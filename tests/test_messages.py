# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Snapshot tests for tcbot.modules.messages.M.

These tests pin every string in the class so accidental edits are caught
immediately. They do NOT test all user-facing copy (most is inline in modules).
"""

from __future__ import annotations

from tcbot.modules.messages import M


def test_community_exact_bytes() -> None:
    assert M.COMMUNITY_NAME == "TCF - 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯"


def test_spec_locked_auth_strings() -> None:
    assert M.NOT_AUTHORIZED         == "You are not authorized."
    assert M.CANNOT_RESOLVE_USER    == "Cannot resolve user."
    assert M.USER_NOT_BANNED        == "User is not banned."
    assert M.ALREADY_TC_ADMIN       == "Already a Transsion Core Admin."
    assert M.NOT_TC_ADMIN           == "Not a Transsion Core Admin."
    assert M.INVALID_OR_EXPIRED_BAN == "Invalid or expired ban."


def test_ban_success_format_placeholder() -> None:
    rendered = M.BAN_SUCCESS.format(target_id=42, reason="spam")
    assert "42" in rendered and "spam" in rendered


def test_unban_success_format_placeholder() -> None:
    assert "42" in M.UNBAN_SUCCESS.format(target_id=42)


def test_promote_owner_done_format_placeholder() -> None:
    assert "7" in M.PROMOTE_OWNER_DONE.format(target_id=7)


def test_transfer_done_format_placeholder() -> None:
    assert "7" in M.TRANSFER_DONE.format(target_id=7)


def test_appeal_decision_strings_contain_reviewer_placeholder() -> None:
    link = '<a href="#">Bob</a>'
    assert link in M.APPEAL_DECISION_APPROVED.format(reviewer_link=link)
    assert link in M.APPEAL_DECISION_REJECTED.format(reviewer_link=link)


def test_no_emoji_in_any_message_attribute() -> None:
    emoji_ranges = [(0x1F300, 0x1FAFF), (0x1F600, 0x1F64F)]
    for attr in vars(M.__class__):
        if attr.startswith("_"):
            continue
        value = getattr(M, attr, None)
        if not isinstance(value, str):
            continue
        for ch in value:
            cp = ord(ch)
            for lo, hi in emoji_ranges:
                assert not (lo <= cp <= hi), (
                    f"Emoji U+{cp:04X} found in M.{attr}"
                )
