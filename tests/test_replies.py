# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.replies - shared reply/help-text constants."""

from __future__ import annotations

import re

from tcbot.modules.helper import replies

# ─────────────────────────── Fixtures ───────────────────────────── #

_ALL_CONSTANTS: list[tuple[str, str]] = [
    ("TARGET_SYNTAX", replies.TARGET_SYNTAX),
    ("ERR_NO_TARGET", replies.ERR_NO_TARGET),
    ("ERR_CANNOT_RESOLVE", replies.ERR_CANNOT_RESOLVE),
    ("ERR_CANT_FIND_USER", replies.ERR_CANT_FIND_USER),
    ("ERR_ROLE_VERIFY", replies.ERR_ROLE_VERIFY),
    ("ERR_GROUP_ONLY", replies.ERR_GROUP_ONLY),
    ("ERR_NO_CONNECTED_GROUPS", replies.ERR_NO_CONNECTED_GROUPS),
    ("ERR_GROUP_NOT_FOUND", replies.ERR_GROUP_NOT_FOUND),
    ("CONTEXT_BOT_OR_GROUP", replies.CONTEXT_BOT_OR_GROUP),
    ("CONTEXT_EXEC_OR_GROUP", replies.CONTEXT_EXEC_OR_GROUP),
    ("CONTEXT_ANYONE", replies.CONTEXT_ANYONE),
    ("PERM_DEV_ABOVE", replies.PERM_DEV_ABOVE),
    ("PERM_TESTER_ABOVE", replies.PERM_TESTER_ABOVE),
    ("PERM_FOUNDER_ONLY", replies.PERM_FOUNDER_ONLY),
    ("PERM_STAFF_ONLY", replies.PERM_STAFF_ONLY),
    ("PERM_ADMIN_ABOVE", replies.PERM_ADMIN_ABOVE),
    ("NO_REASON", replies.NO_REASON),
    ("SEC_COMMANDS", replies.SEC_COMMANDS),
    ("SEC_WHO", replies.SEC_WHO),
    ("SEC_WHERE", replies.SEC_WHERE),
    ("SEC_WHAT", replies.SEC_WHAT),
    ("SEC_EXAMPLES", replies.SEC_EXAMPLES),
    ("SEC_TARGET", replies.SEC_TARGET),
]

_PERM_CONSTANTS: list[tuple[str, str]] = [
    ("PERM_DEV_ABOVE", replies.PERM_DEV_ABOVE),
    ("PERM_TESTER_ABOVE", replies.PERM_TESTER_ABOVE),
    ("PERM_FOUNDER_ONLY", replies.PERM_FOUNDER_ONLY),
    ("PERM_STAFF_ONLY", replies.PERM_STAFF_ONLY),
    ("PERM_ADMIN_ABOVE", replies.PERM_ADMIN_ABOVE),
]

# Broad Unicode pictograph / emoji block
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
# Em-dash and en-dash
_DASH_RE = re.compile(r"\u2014|\u2013")


# ─────────────────────── non-empty checks ──────────────────────── #


def test_all_constants_are_non_empty_strings() -> None:
    for name, value in _ALL_CONSTANTS:
        assert isinstance(value, str), f"{name} is not a str"
        assert value.strip(), f"{name} is empty or whitespace-only"


# ───────────────────── emoji / em-dash policy ───────────────────── #


def test_no_emoji_in_any_constant() -> None:
    for name, value in _ALL_CONSTANTS:
        assert not _EMOJI_RE.search(value), f"Emoji found in {name}: {value!r}"


def test_no_em_dash_in_any_constant() -> None:
    for name, value in _ALL_CONSTANTS:
        assert not _DASH_RE.search(value), f"Em/en-dash found in {name}: {value!r}"


# ─────────────────── permission constant format ─────────────────── #


def test_perm_constants_end_with_period() -> None:
    """Permission labels read as sentences and must end with a period."""
    for name, value in _PERM_CONSTANTS:
        assert value.endswith("."), f"{name!r} must end with '.': {value!r}"


# ──────────────────── distinct values check ─────────────────────── #


def test_all_constants_are_distinct() -> None:
    """No two constants should have identical text (catches copy-paste errors)."""
    values = [v for _, v in _ALL_CONSTANTS]
    assert len(values) == len(set(values)), "Duplicate constant values detected"


# ─────────────────── known content spot-checks ─────────────────── #


def test_err_no_target_mentions_reply_or_id() -> None:
    """Error message should guide the user on how to specify a target."""
    low = replies.ERR_NO_TARGET.lower()
    assert "reply" in low or "user" in low or "id" in low


def test_context_exec_or_group_references_exec_or_group() -> None:
    low = replies.CONTEXT_EXEC_OR_GROUP.lower()
    assert "exec" in low or "group" in low or "pm" in low


def test_perm_founder_only_says_founder() -> None:
    assert "Founder" in replies.PERM_FOUNDER_ONLY


def test_perm_staff_only_mentions_staff_or_admin() -> None:
    low = replies.PERM_STAFF_ONLY.lower()
    assert "staff" in low or "admin" in low


def test_perm_dev_above_mentions_developer() -> None:
    low = replies.PERM_DEV_ABOVE.lower()
    assert "developer" in low or "dev" in low
