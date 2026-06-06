# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for TypedDict document schemas in tcbot.database.documents."""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database import documents as docs
from tcbot.database.types import BanId, ChatId, GroupId, UserId

# ───────────────────── Literal alias constants ───────────────────── #


def test_ban_status_values() -> None:
    """BanStatus covers exactly active, expired, revoked."""
    args = docs.BanStatus.__args__  # type: ignore[attr-defined]
    assert set(args) == {"active", "expired", "revoked"}


def test_role_name_values() -> None:
    """RoleName covers exactly the four federation roles."""
    args = docs.RoleName.__args__  # type: ignore[attr-defined]
    assert set(args) == {"founder", "admin", "developer", "tester"}


def test_request_status_values() -> None:
    """RequestStatus covers pending, approved, and rejected."""
    args = docs.RequestStatus.__args__  # type: ignore[attr-defined]
    assert set(args) == {"pending", "approved", "rejected"}


# ──────────────────── TypedDict key membership ───────────────────── #


def test_admin_doc_keys() -> None:
    """AdminDoc declares user_id, promoted_by, promoted_date."""
    keys = set(docs.AdminDoc.__annotations__)
    assert "user_id" in keys
    assert "promoted_by" in keys
    assert "promoted_date" in keys


def test_ban_doc_keys() -> None:
    """BanDoc declares the core ban fields used by bans_db."""
    keys = set(docs.BanDoc.__annotations__)
    assert {
        "ban_id",
        "banned_user_id",
        "reason",
        "admin_user_id",
        "is_active",
    }.issubset(keys)


def test_group_doc_keys() -> None:
    """GroupDoc declares the group tracking fields."""
    keys = set(docs.GroupDoc.__annotations__)
    assert {"chat_id", "title", "added_by", "is_active"}.issubset(keys)


def test_pending_group_doc_keys() -> None:
    """PendingGroupDoc has chat_id, owner_id, and message_id."""
    keys = set(docs.PendingGroupDoc.__annotations__)
    assert {"chat_id", "owner_id", "message_id"}.issubset(keys)


def test_role_doc_keys() -> None:
    """RoleDoc declares user_id, role, assigned_by, and assigned_at."""
    keys = set(docs.RoleDoc.__annotations__)
    assert {"user_id", "role", "assigned_by", "assigned_at"}.issubset(keys)


def test_user_doc_keys() -> None:
    """UserDoc declares user_id and at least the three name fields."""
    keys = set(docs.UserDoc.__annotations__)
    assert {"user_id", "username", "first_name", "last_name"}.issubset(keys)


def test_warn_doc_keys() -> None:
    """WarnDoc has the moderation-relevant warn fields."""
    keys = set(docs.WarnDoc.__annotations__)
    assert {"user_id", "reason", "admin_id", "chat_id", "timestamp"}.issubset(keys)


def test_warn_count_doc_keys() -> None:
    """WarnCountDoc tracks per-user per-chat warning totals."""
    keys = set(docs.WarnCountDoc.__annotations__)
    assert {"user_id", "chat_id", "count"}.issubset(keys)


def test_promotion_request_doc_keys() -> None:
    """PromotionRequestDoc has request_id, target_id, and status."""
    keys = set(docs.PromotionRequestDoc.__annotations__)
    assert {"request_id", "target_id", "status"}.issubset(keys)


# ───────────────────── Runtime construction ─────────────────────── #

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_admin_doc_construction() -> None:
    """AdminDoc can be constructed as a regular dict at runtime."""
    doc: docs.AdminDoc = {
        "user_id": UserId(42),
        "promoted_by": UserId(1),
        "promoted_date": _NOW,
    }
    assert doc["user_id"] == 42


def test_ban_doc_construction() -> None:
    """BanDoc can be constructed with minimal fields."""
    doc: docs.BanDoc = {
        "ban_id": BanId("abc123"),
        "banned_user_id": UserId(99),
        "reason": "spam",
        "admin_user_id": UserId(1),
        "is_active": True,
    }
    assert doc["reason"] == "spam"
    assert doc["is_active"] is True


def test_group_doc_construction() -> None:
    """GroupDoc can be constructed and is_active is accessible."""
    doc: docs.GroupDoc = {
        "chat_id": GroupId(-1001234567890),
        "title": "Test Group",
        "added_by": UserId(7),
        "is_active": True,
    }
    assert doc["is_active"] is True


def test_warn_doc_construction() -> None:
    """WarnDoc construction includes chat_id and timestamp."""
    doc: docs.WarnDoc = {
        "user_id": UserId(5),
        "reason": "rule violation",
        "admin_id": UserId(1),
        "chat_id": ChatId(-100),
        "timestamp": _NOW,
    }
    assert doc["reason"] == "rule violation"


def test_promotion_request_doc_construction() -> None:
    """PromotionRequestDoc stores all request metadata."""
    doc: docs.PromotionRequestDoc = {
        "request_id": "req-001",
        "target_id": UserId(88),
        "username": "alice",
        "first_name": "Alice",
        "promoted_by": UserId(1),
        "status": "pending",
        "requested_date": _NOW,
        "resolved_date": None,
        "resolved_by": None,
    }
    assert doc["status"] == "pending"
    assert doc["resolved_date"] is None
