# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for domain primitive NewTypes in tcbot.database.types."""

from __future__ import annotations

from tcbot.database.types import BanId, ChatId, GroupId, UserId

# ────────────────────── Runtime identity ─────────────────────────── #
# NewType() in Python 3.10+ is the identity function at runtime:
# calling the constructor just returns the raw value.


def test_user_id_is_int() -> None:
    """UserId is backed by int at runtime."""
    uid = UserId(123)
    assert isinstance(uid, int)
    assert uid == 123


def test_group_id_is_int_and_typically_negative() -> None:
    """GroupId is backed by int; convention is negative for supergroups."""
    gid = GroupId(-1001234567890)
    assert isinstance(gid, int)
    assert gid < 0


def test_chat_id_is_int() -> None:
    """ChatId is backed by int."""
    cid = ChatId(-9000)
    assert isinstance(cid, int)
    assert cid == -9000


def test_ban_id_is_str() -> None:
    """BanId is backed by str."""
    bid = BanId("abc123")
    assert isinstance(bid, str)
    assert bid == "abc123"


# ──────────────────────── Arithmetic / comparison ───────────────────── #


def test_user_id_equality_with_plain_int() -> None:
    """UserId equals its plain int counterpart."""
    assert UserId(42) == 42


def test_group_id_comparison() -> None:
    """GroupId supports comparison operators like its base int."""
    assert GroupId(-100) < GroupId(-50)


def test_chat_id_addition() -> None:
    """ChatId arithmetic produces an int (NewType has no special operators)."""
    result = ChatId(100) + ChatId(200)
    assert result == 300


def test_ban_id_concatenation() -> None:
    """BanId string operations work as expected for a str NewType."""
    prefix = "BAN-"
    bid = BanId("x7y8z9")
    assert (prefix + bid) == "BAN-x7y8z9"


def test_ban_id_length() -> None:
    """BanId supports len() as a normal str."""
    bid = BanId("abcde")
    assert len(bid) == 5


# ──────────────────────── Zero / empty values ───────────────────────── #


def test_user_id_zero() -> None:
    """UserId(0) is falsy, like int 0."""
    assert not UserId(0)


def test_ban_id_empty_string() -> None:
    """BanId('') is falsy, like an empty str."""
    assert not BanId("")


# ─────────────────────── Distinct type names ────────────────────────── #


def test_newtype_names_are_distinct() -> None:
    """Each NewType has its own __qualname__ so type checkers treat them differently."""
    assert UserId.__qualname__ != GroupId.__qualname__
    assert GroupId.__qualname__ != ChatId.__qualname__
    assert UserId.__qualname__ != BanId.__qualname__
