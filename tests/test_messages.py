# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Snapshot tests for the central :class:`Messages` namespace.

The PROMPT specification fixes several user-facing strings byte-for-byte.
Tests below guard against accidental edits to those exact phrasings.
"""
from __future__ import annotations

from tgbot_tcf.modules.messages import M


def test_branding_line_matches_italicized_unicode() -> None:
    assert M.BRANDING_LINE == "𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯"


def test_spec_locked_strings_are_byte_exact() -> None:
    assert M.NOT_AUTHORIZED == "You are not authorized."
    assert M.CANNOT_RESOLVE_USER == "Cannot resolve user."
    assert M.USER_NOT_BANNED == "User is not banned."
    assert M.ALREADY_TC_ADMIN == "Already a Transsion Core Admin."
    assert M.NOT_TC_ADMIN == "Not a Transsion Core Admin."
    assert M.INVALID_OR_EXPIRED_BAN == "Invalid or expired ban."


def test_format_placeholders_resolve() -> None:
    assert M.BAN_SUCCESS.format(target_id=42, reason="spam") == (
        "User 42 has been banned from the Transsion Core. Reason: spam"
    )
    assert M.UNBAN_SUCCESS.format(target_id=42) == (
        "User 42 has been unbanned from the Transsion Core."
    )
    assert M.PROMOTE_OWNER_DONE.format(target_id=7) == (
        "User 7 is now a Transsion Core Admin."
    )
    assert M.TRANSFER_DONE.format(target_id=7) == "Ownership transferred to 7."


def test_appeal_decision_templates_render_reviewer_link() -> None:
    rendered = M.APPEAL_DECISION_APPROVED.format(reviewer_link="<a>Bob</a>")
    assert "<a>Bob</a>" in rendered
    assert "User has been unbanned" in rendered


def test_no_emoji_in_any_message() -> None:
    """No code point above U+2600 is an emoji-region character we use here."""
    forbidden_ranges = [
        (0x1F300, 0x1FAFF),  # symbols & pictographs, emoticons, transport
        (0x2600, 0x27BF),    # misc symbols + dingbats
    ]
    for attr in dir(M):
        if attr.startswith("_"):
            continue
        value = getattr(M, attr)
        if not isinstance(value, str):
            continue
        for ch in value:
            cp = ord(ch)
            for lo, hi in forbidden_ranges:
                assert not (lo <= cp <= hi), (
                    f"Emoji-range character U+{cp:04X} found in M.{attr}"
                )
