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
ActionType = Literal["warn", "mute", "ban", "kick"]
ActionStatus = Literal["active", "completed", "revoked", "expired", "superseded"]
ScopeType = Literal["community", "chat"]


class AdminDoc(TypedDict, total=False):
    """Row shape of a staff assignment."""

    user_id: UserId
    role_key: str
    assigned_by: UserId
    assigned_at: datetime


class BanDoc(TypedDict, total=False):
    """Row shape of a community ban.

    The decision lives in ``moderation_actions`` and the Telegram
    messages beside it in ``moderation_messages``. The helper joins
    them, so the reader sees one document.
    """

    id: int
    ban_id: BanId
    external_ref: str
    banned_user_id: UserId
    reason: str
    admin_user_id: UserId
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


class RoleDoc(TypedDict, total=False):
    """Row shape of a user's role assignment."""

    user_id: UserId
    role_key: str
    assigned_by: UserId
    assigned_at: datetime
    status: str
    expires_at: datetime | None


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


class UserSettingsDoc(TypedDict, total=False):
    """Row shape of a per-user settings row.

    Lives in its own ``user_settings`` table so preference-only rows never
    inflate the user listings.
    """

    user_id: UserId
    locale: str | None
    timezone: str | None
    preferences: dict[str, object]


class KickDoc(TypedDict, total=False):
    """Row shape of a single kick decision (append-only audit record)."""

    user_id: UserId
    chat_id: ChatId
    reason: str
    admin_id: UserId
    timestamp: datetime


class MuteDoc(TypedDict, total=False):
    """Row shape of a single mute decision (append-only audit record).

    ``duration_secs`` is absent for permanent mutes and present (int) for
    timed mutes, reflecting how long the restriction was intended to last.
    """

    user_id: UserId
    chat_id: ChatId | None
    reason: str
    admin_id: UserId
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

    user_id: UserId
    reason: str
    admin_id: UserId
    chat_id: ChatId
    timestamp: datetime


class WarnCountDoc(TypedDict, total=False):
    """Row shape of the running warning total for a user in a chat."""

    user_id: UserId
    chat_id: ChatId
    count: int


class ChatSettingsDoc(TypedDict, total=False):
    """Row shape of the configuration of one group."""

    chat_id: GroupId
    locale: str | None
    timezone: str | None
    settings: dict[str, object]


class ModerationActionDoc(TypedDict, total=False):
    """Row shape of one moderation decision."""

    id: int
    action_type: ActionType
    scope_type: ScopeType
    target_user_id: UserId
    actor_user_id: UserId
    reason: str
    duration_seconds: int | None
    created_at: datetime
    expires_at: datetime | None
    status: ActionStatus
    external_ref: str
    case_id: int
    evidence_upload_id: int | None
    supersedes_action_id: int | None
    action_origin: str
    chat_id: int | None
    origin_chat_id: int | None
    metadata: dict[str, object]


class ModerationCaseDoc(TypedDict, total=False):
    """Row shape of one moderation case."""

    id: int
    public_id: str
    subject_user_id: UserId
    case_type: str
    title: str
    summary: str | None
    severity: str
    status: str
    source: str
    opened_by_user_id: UserId | None
    assigned_to_user_id: UserId | None
    closed_by_user_id: UserId | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    requires_evidence: bool
    metadata: dict[str, object]


class EvidenceUploadDoc(TypedDict, total=False):
    """Row shape of one archived evidence batch."""

    id: int
    case_id: int
    uploaded_by_user_id: UserId | None
    destination_chat_id: int
    destination_thread_id: int | None
    is_required: bool
    expected_item_count: int
    status: str
    primary_message_id: int | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    updated_at: datetime


class AppealDoc(TypedDict, total=False):
    """Row shape of one appeal against a ban."""

    id: int
    action_id: int
    appellant_user_id: UserId
    appeal_text: str
    status: str
    submitted_at: datetime
    resolved_at: datetime | None
    reviewed_by_user_id: UserId | None
    decision_note: str | None


class EnforcementRunDoc(TypedDict, total=False):
    """Row shape of one enforcement operation."""

    id: int
    action_id: int
    operation: str
    idempotency_key: str
    requested_by_user_id: UserId | None
    status: str
    target_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EnforcementTargetDoc(TypedDict, total=False):
    """Row shape of the per-group result of one enforcement run."""

    id: int
    run_id: int
    chat_id: GroupId
    status: str
    attempt_count: int
    last_error_kind: str | None
    last_error_code: str | None
    next_retry_at: datetime | None
    completed_at: datetime | None


class AuditEventDoc(TypedDict, total=False):
    """Row shape of one audit event."""

    id: int
    actor_user_id: UserId | None
    subject_user_id: UserId | None
    event_key: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, object]
    occurred_at: datetime
    case_id: int | None
    action_id: int | None
    correlation_id: str | None
    operation_id: str | None


class CommunityProfileDoc(TypedDict, total=False):
    """Row shape of the community profile."""

    singleton_key: str
    community: str | None
    description: str | None
    default_locale: str | None
    timezone: str | None
    settings: dict[str, object]
    updated_at: datetime


class PromotionRequestDoc(TypedDict, total=False):
    """Row shape of a pending or resolved staff promotion request."""

    request_id: str
    target_id: UserId
    username: str | None
    first_name: str
    requested_role_key: str
    promoted_by: UserId
    status: RequestStatus
    requested_date: datetime
    resolved_date: datetime | None
    resolved_by: UserId | None
    decision_note: str | None
