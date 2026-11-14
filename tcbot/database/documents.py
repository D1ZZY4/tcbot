# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""TypedDict row schemas for the PostgreSQL tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

from tcbot.database.types import BanId, ChatId, GroupId, UserId

if TYPE_CHECKING:
    from datetime import datetime

RoleName = Literal["owner", "admin", "developer", "moderator"]
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]
ActionStatus = Literal["active", "completed", "revoked", "expired", "superseded"]
ScopeType = Literal["community", "chat"]


class AdminDoc(TypedDict, total=False):
    """Row shape of a staff assignment."""

    user_id: UserId
    role_key: str
    assigned_by_user_id: UserId
    assigned_at: datetime


class BanDoc(TypedDict, total=False):
    """Row shape of a community ban.

    The decision lives in ``moderation_actions`` and the Telegram
    messages beside it in ``moderation_messages``. The helper joins
    them, so the reader sees one document. The target and the actor carry
    the names the decision table gives them, so one vocabulary names
    them across every moderation document.
    """

    id: int
    ban_id: BanId
    target_user_id: UserId
    reason: str
    actor_user_id: UserId
    proof_message_id: int
    log_message_id: int
    previous_proof_message_id: int | None
    previous_log_message_id: int | None
    timestamp: datetime
    updated_timestamp: datetime | None
    until_date: datetime | None
    duration_str: str | None
    duration_seconds: int | None
    is_active: bool
    status: ActionStatus
    update_count: int
    review_message_id: int | None
    review_timestamp: datetime | None
    appeal_log_msg_id: int | None
    appeal_submitted_at: datetime | None
    appeal_link: str | None
    rejected_by_id: int | None
    rejected_at: datetime | None
    case_id: int
    evidence_upload_id: int | None
    action_origin: str
    scope_type: ScopeType
    origin_chat_id: int | None
    metadata: dict[str, object]


class GroupDoc(TypedDict, total=False):
    """Row shape of a connected group."""

    chat_id: GroupId
    title: str
    added_by: UserId
    added_date: datetime
    is_active: bool
    locale: str | None


class PendingGroupDoc(TypedDict, total=False):
    """Row shape of a group awaiting connection approval."""

    chat_id: ChatId
    title: str
    owner_id: UserId
    message_id: int
    added_date: datetime
    request_id: int
    status: RequestStatus


class RoleRefDoc(TypedDict, total=False):
    """Minimal reference document storing only a user ID for role index lookups."""

    user_id: UserId


class UserDoc(TypedDict, total=False):
    """Row shape of a Telegram user profile."""

    user_id: UserId
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    is_bot: bool
    is_premium: bool
    first_seen_at: datetime
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
    erased_at: datetime | None
    erasure_reason: str | None


class KickDoc(TypedDict, total=False):
    """Row shape of a single kick decision (append-only audit record)."""

    target_user_id: UserId
    chat_id: ChatId
    reason: str
    actor_user_id: UserId
    timestamp: datetime


class MuteDoc(TypedDict, total=False):
    """Row shape of a single mute decision (append-only audit record).

    ``duration_secs`` is absent for permanent mutes and present (int) for
    timed mutes, reflecting how long the restriction was intended to last.
    """

    target_user_id: UserId
    chat_id: ChatId | None
    reason: str
    actor_user_id: UserId
    timestamp: datetime
    duration_secs: int | None


class ActiveMuteDoc(TypedDict, total=False):
    """Row shape of a currently active community mute.

    The live mute is the decision whose status is ``active``:
    ``until_date`` is ``None`` for a permanent mute or a UTC datetime for a
    timed mute. Expired timed mutes are filtered out at query time.
    """

    user_id: UserId
    until_date: datetime | None
    timestamp: datetime


class WarnDoc(TypedDict, total=False):
    """Row shape of a single warning issued to a user."""

    target_user_id: UserId
    reason: str
    actor_user_id: UserId
    chat_id: ChatId
    timestamp: datetime


class PromotionRequestDoc(TypedDict, total=False):
    """Row shape of a pending or resolved staff promotion request.

    The document carries the column names of ``promotion_requests`` so a
    reader does not need a second vocabulary for the same fields.
    """

    request_id: str
    target_user_id: UserId
    username: str | None
    first_name: str
    requested_role_key: str
    requested_by_user_id: UserId
    status: RequestStatus
    requested_at: datetime
    resolved_at: datetime | None
    resolved_by_user_id: UserId | None
    decision_note: str | None
