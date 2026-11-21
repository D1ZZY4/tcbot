# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""TypedDict row schemas for the PostgreSQL tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

from tcbot.database.types import BanId, ChatId, GroupId, UserId

if TYPE_CHECKING:
    from datetime import datetime

RequestStatus = Literal["pending", "approved", "rejected", "cancelled", "expired"]
ActionStatus = Literal[
    "active", "completed", "revoked", "expired", "superseded", "failed"
]
ScopeType = Literal["community", "chat"]
EvidenceMediaType = Literal[
    "photo",
    "video",
    "animation",
    "document",
    "audio",
    "voice",
    "video_note",
    "sticker",
]


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
    enforcement_run_id: int | None
    action_origin: str
    scope_type: ScopeType
    origin_chat_id: int | None
    rules: list[str]
    metadata: dict[str, object]


class EvidenceItemDoc(TypedDict, total=False):
    """Row shape of one archived proof item.

    One row describes one Telegram message that actually landed in the
    evidence destination, so a gallery is recorded as its individual
    photos, videos, or files instead of a single ``photo`` placeholder.
    """

    media_type: EvidenceMediaType
    archive_message_id: int
    item_order: int
    media_group_id: str | None
    file_unique_id: str | None
    mime_type: str | None
    file_size_bytes: int | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    file_name: str | None
    source_chat_id: int | None
    source_message_id: int | None
    caption_text: str | None


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
    status: ActionStatus


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
    requested_duration_secs: int | None


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
    expires_at: datetime | None
    resolved_at: datetime | None
    resolved_by_user_id: UserId | None
    decision_note: str | None


# ─────────────────────────── Rules ─────────────────────────────── #


class RuleSetDoc(TypedDict, total=False):
    """Row shape of one rule set."""

    id: int
    scope_type: ScopeType
    chat_id: ChatId | None
    rule_set_key: str
    name: str
    description: str | None
    is_active: bool
    requires_acknowledgement: bool
    created_at: datetime
    updated_at: datetime


class RuleVersionDoc(TypedDict, total=False):
    """Row shape of one rule set version."""

    id: int
    rule_set_id: int
    version_number: int
    locale: str
    status: Literal["draft", "published", "superseded", "archived"]
    change_summary: str | None
    created_by_user_id: UserId | None
    published_by_user_id: UserId | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuleCategoryDoc(TypedDict, total=False):
    """Row shape of one category in the catalogue."""

    id: int
    rule_set_id: int
    category_key: str
    title: str
    sort_order: int
    is_active: bool


class RuleItemDoc(TypedDict, total=False):
    """Row shape of one rule item, including its category snapshot."""

    id: int
    rule_set_version_id: int
    rule_key: str
    category_key: str
    category_title: str | None
    category_sort_order: int | None
    title: str
    body: str
    content_format: Literal["plain_text", "markdown"]
    sort_order: int
    is_mandatory: bool
    reference_url: str | None
    metadata: dict[str, object]


class RulePublicationDoc(TypedDict, total=False):
    """Row shape of one channel message slot."""

    id: int
    rule_set_id: int
    rule_set_version_id: int
    locale: str
    chat_id: ChatId
    message_thread_id: int | None
    category_key: str
    part_index: int
    message_id: int | None
    content_hash: str | None
    run_id: int | None
    status: Literal["pending", "synced", "failed", "missing", "retired", "deleted"]
    last_error: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuleRunDoc(TypedDict, total=False):
    """Row shape of one publish-and-sync run."""

    id: int
    rule_set_id: int
    rule_set_version_id: int
    chat_id: ChatId
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime | None
    lease_expires_at: datetime
    error: str | None


class RuleAckDoc(TypedDict, total=False):
    """Row shape of one user's acceptance of one published version."""

    id: int
    rule_set_version_id: int
    user_id: UserId
    context_chat_id: ChatId | None
    acknowledgement_method: Literal[
        "inline_button", "command", "join_gate", "admin_recorded", "api"
    ]
    telegram_message_id: int | None
    acknowledged_at: datetime
    metadata: dict[str, object]
