# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Moderation case, action, appeal, evidence, and audit tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, enum_check, metadata

# * An investigation against one subject. A case holds the evidence and
# * the rules; the action holds the decision.
moderation_cases = Table(
    "moderation_cases",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column(
        "public_id",
        Text,
        nullable=False,
        server_default=text("gen_random_uuid()::text"),
    ),
    Column("subject_user_id", BigInteger, nullable=False),
    Column("case_type", Text, nullable=False, server_default="rule_violation"),
    Column("title", Text, nullable=False),
    Column("summary", Text, nullable=True),
    Column("severity", Text, nullable=False, server_default="unknown"),
    Column("status", Text, nullable=False, server_default="open"),
    Column("source", Text, nullable=False, server_default="manual"),
    Column("opened_by_user_id", BigInteger, nullable=True),
    Column("assigned_to_user_id", BigInteger, nullable=True),
    Column("closed_by_user_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("requires_evidence", Boolean, nullable=False, server_default=text("false")),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["subject_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_cases_subject",
    ),
    ForeignKeyConstraint(
        ["opened_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_cases_opened_by",
    ),
    ForeignKeyConstraint(
        ["assigned_to_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_cases_assigned_to",
    ),
    ForeignKeyConstraint(
        ["closed_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_cases_closed_by",
    ),
    UniqueConstraint("public_id", name="uq_moderation_cases_public_id"),
    # * The composite key lets an action point at the case of its own
    # * subject: a ban cannot be filed against another case.
    UniqueConstraint("id", "subject_user_id", name="uq_moderation_cases_id_subject"),
    CheckConstraint("btrim(case_type) <> ''", name="ck_moderation_cases_type"),
    CheckConstraint("btrim(title) <> ''", name="ck_moderation_cases_title"),
    enum_check(
        "ck_moderation_cases_severity",
        "severity",
        "unknown",
        "low",
        "medium",
        "high",
        "critical",
    ),
    enum_check(
        "ck_moderation_cases_status",
        "status",
        "open",
        "collecting_evidence",
        "evidence_failed",
        "under_review",
        "escalated",
        "resolved",
        "dismissed",
        "cancelled",
    ),
    enum_check(
        "ck_moderation_cases_source", "source", "manual", "system", "automated", "ai"
    ),
)

Index("ix_moderation_cases_subject", moderation_cases.c.subject_user_id)
Index("ix_moderation_cases_status", moderation_cases.c.status)
Index("ix_moderation_cases_created", moderation_cases.c.created_at.desc())
Index("ix_moderation_cases_assigned", moderation_cases.c.assigned_to_user_id)
Index("ix_moderation_cases_opened_by", moderation_cases.c.opened_by_user_id)
Index("ix_moderation_cases_closed_by", moderation_cases.c.closed_by_user_id)

# * Which rules a case is about, and who linked them.
moderation_case_rules = Table(
    "moderation_case_rules",
    metadata,
    Column("case_id", BigInteger, nullable=False, autoincrement=False),
    Column("rule_item_id", BigInteger, nullable=False, autoincrement=False),
    Column("linked_by_user_id", BigInteger, nullable=True),
    Column("attribution_source", Text, nullable=False, server_default="moderator"),
    Column("note", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("context_chat_id", BigInteger, nullable=True),
    PrimaryKeyConstraint("case_id", "rule_item_id"),
    ForeignKeyConstraint(
        ["case_id"],
        ["moderation_cases.id"],
        name="fk_moderation_case_rules_case",
    ),
    ForeignKeyConstraint(
        ["rule_item_id"],
        ["rule_items.id"],
        name="fk_moderation_case_rules_rule_item",
    ),
    ForeignKeyConstraint(
        ["linked_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_case_rules_linked_by",
    ),
    ForeignKeyConstraint(
        ["context_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_moderation_case_rules_context_chat",
    ),
    enum_check(
        "ck_moderation_case_rules_attribution",
        "attribution_source",
        "moderator",
        "system",
        "automated",
        "ai",
    ),
)

Index("ix_moderation_case_rules_rule_item", moderation_case_rules.c.rule_item_id)
Index("ix_moderation_case_rules_context_chat", moderation_case_rules.c.context_chat_id)
Index("ix_moderation_case_rules_linked_by", moderation_case_rules.c.linked_by_user_id)

# * One batch of archived evidence for one case.
moderation_evidence_uploads = Table(
    "moderation_evidence_uploads",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("case_id", BigInteger, nullable=False),
    Column("uploaded_by_user_id", BigInteger, nullable=True),
    Column("destination_chat_id", BigInteger, nullable=False),
    Column("destination_thread_id", BigInteger, nullable=True),
    Column("is_required", Boolean, nullable=False, server_default=text("false")),
    Column("expected_item_count", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("idempotency_key", Text, nullable=True),
    Column("primary_message_id", BigInteger, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("failure_code", Text, nullable=True),
    Column("failure_detail", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["case_id"],
        ["moderation_cases.id"],
        name="fk_moderation_evidence_uploads_case",
    ),
    ForeignKeyConstraint(
        ["uploaded_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_evidence_uploads_uploader",
    ),
    ForeignKeyConstraint(
        ["destination_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_moderation_evidence_uploads_destination",
    ),
    # * The composite keys let an action point at the evidence batch of
    # * its own case, and let a batch point at its first archived item.
    UniqueConstraint("id", "case_id", name="uq_moderation_evidence_uploads_id_case"),
    UniqueConstraint(
        "id",
        "destination_chat_id",
        name="uq_moderation_evidence_uploads_id_destination",
    ),
    CheckConstraint(
        "destination_thread_id IS NULL OR destination_thread_id > 0",
        name="ck_moderation_evidence_uploads_thread",
    ),
    CheckConstraint(
        "expected_item_count > 0", name="ck_moderation_evidence_uploads_expected"
    ),
    enum_check(
        "ck_moderation_evidence_uploads_status",
        "status",
        "queued",
        "uploading",
        "completed",
        "partial",
        "failed",
        "cancelled",
    ),
    CheckConstraint(
        "idempotency_key IS NULL OR btrim(idempotency_key) <> ''",
        name="ck_moderation_evidence_uploads_idempotency",
    ),
)

Index("ix_moderation_evidence_uploads_case", moderation_evidence_uploads.c.case_id)
Index("ix_moderation_evidence_uploads_status", moderation_evidence_uploads.c.status)
Index(
    "ix_moderation_evidence_uploads_destination",
    moderation_evidence_uploads.c.destination_chat_id,
)
Index(
    "ix_moderation_evidence_uploads_uploader",
    moderation_evidence_uploads.c.uploaded_by_user_id,
)

# * One archived Telegram message. The raw media stays in the archive
# * chat; the row keeps the references and the ordering.
moderation_evidence_items = Table(
    "moderation_evidence_items",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("upload_id", BigInteger, nullable=False),
    Column("destination_chat_id", BigInteger, nullable=False),
    Column("archive_message_id", BigInteger, nullable=False),
    Column("source_chat_id", BigInteger, nullable=True),
    Column("source_message_id", BigInteger, nullable=True),
    Column("media_group_id", Text, nullable=True),
    Column("media_type", Text, nullable=False),
    Column("file_unique_id", Text, nullable=True),
    Column("mime_type", Text, nullable=True),
    Column("file_size_bytes", BigInteger, nullable=True),
    Column("item_order", Integer, nullable=False),
    Column("sha256_hex", Text, nullable=True),
    Column("archive_message_url", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("file_name", Text, nullable=True),
    Column("caption_text", Text, nullable=True),
    Column("duration_seconds", Integer, nullable=True),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    PrimaryKeyConstraint("id"),
    UniqueConstraint(
        "upload_id", "archive_message_id", name="uq_moderation_evidence_items_message"
    ),
    CheckConstraint(
        "archive_message_id > 0", name="ck_moderation_evidence_items_archive"
    ),
    CheckConstraint(
        "source_message_id IS NULL OR source_message_id > 0",
        name="ck_moderation_evidence_items_source_message",
    ),
    enum_check(
        "ck_moderation_evidence_items_media_type",
        "media_type",
        "photo",
        "video",
        "animation",
        "document",
        "audio",
        "voice",
        "video_note",
        "sticker",
    ),
    CheckConstraint("item_order >= 0", name="ck_moderation_evidence_items_order"),
    CheckConstraint(
        "sha256_hex IS NULL OR sha256_hex ~ '^[0-9a-f]{64}$'",
        name="ck_moderation_evidence_items_sha256",
    ),
    CheckConstraint(
        "file_size_bytes IS NULL OR file_size_bytes >= 0",
        name="ck_moderation_evidence_items_size",
    ),
    CheckConstraint(
        "duration_seconds IS NULL OR duration_seconds >= 0",
        name="ck_moderation_evidence_items_duration",
    ),
    CheckConstraint(
        "width IS NULL OR width > 0", name="ck_moderation_evidence_items_width"
    ),
    CheckConstraint(
        "height IS NULL OR height > 0", name="ck_moderation_evidence_items_height"
    ),
    # * The upload and its items reference each other, so the constraint
    # * is deferred to the end of the transaction.
    ForeignKeyConstraint(
        ["upload_id", "destination_chat_id"],
        [
            "moderation_evidence_uploads.id",
            "moderation_evidence_uploads.destination_chat_id",
        ],
        name="fk_moderation_evidence_items_upload_destination",
        deferrable=True,
        initially="DEFERRED",
    ),
)

Index("ix_moderation_evidence_items_upload", moderation_evidence_items.c.upload_id)
Index(
    "ix_moderation_evidence_items_destination",
    moderation_evidence_items.c.destination_chat_id,
)

# * The moderation decision. One row is one decision, whether the scope
# * is the whole community or a single group.
moderation_actions = Table(
    "moderation_actions",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("chat_id", BigInteger, nullable=True),
    Column("action_type", Text, nullable=False),
    Column("target_user_id", BigInteger, nullable=False),
    Column("actor_user_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("duration_seconds", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("status", Text, nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("revoked_by_user_id", BigInteger, nullable=True),
    Column(
        "external_ref",
        Text,
        nullable=False,
        server_default=text("substr(replace(gen_random_uuid()::text, '-', ''), 1, 16)"),
    ),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("case_id", BigInteger, nullable=False),
    Column("supersedes_action_id", BigInteger, nullable=True),
    Column("action_origin", Text, nullable=False, server_default="manual"),
    Column("evidence_upload_id", BigInteger, nullable=True),
    Column("scope_type", Text, nullable=False),
    Column("origin_chat_id", BigInteger, nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["connected_chats.chat_id"],
        name="fk_moderation_actions_chat",
    ),
    ForeignKeyConstraint(
        ["origin_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_moderation_actions_origin_chat",
    ),
    ForeignKeyConstraint(
        ["actor_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_actions_actor",
    ),
    ForeignKeyConstraint(
        ["revoked_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_actions_revoked_by",
    ),
    ForeignKeyConstraint(
        ["target_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_actions_target",
    ),
    ForeignKeyConstraint(
        ["case_id", "target_user_id"],
        ["moderation_cases.id", "moderation_cases.subject_user_id"],
        name="fk_moderation_actions_case_subject",
    ),
    ForeignKeyConstraint(
        ["supersedes_action_id", "target_user_id"],
        ["moderation_actions.id", "moderation_actions.target_user_id"],
        name="fk_moderation_actions_supersedes_subject",
    ),
    ForeignKeyConstraint(
        ["evidence_upload_id", "case_id"],
        ["moderation_evidence_uploads.id", "moderation_evidence_uploads.case_id"],
        name="fk_moderation_actions_evidence_case",
    ),
    UniqueConstraint("external_ref", name="uq_moderation_actions_external_ref"),
    UniqueConstraint("id", "target_user_id", name="uq_moderation_actions_id_target"),
    enum_check(
        "ck_moderation_actions_type", "action_type", "warn", "mute", "ban", "kick"
    ),
    CheckConstraint("btrim(reason) <> ''", name="ck_moderation_actions_reason"),
    CheckConstraint(
        "duration_seconds IS NULL OR duration_seconds >= 0",
        name="ck_moderation_actions_duration",
    ),
    enum_check(
        "ck_moderation_actions_status",
        "status",
        "active",
        "completed",
        "revoked",
        "expired",
        "superseded",
    ),
    CheckConstraint(
        "external_ref ~ '^[a-z0-9]{10,32}$'", name="ck_moderation_actions_external_ref"
    ),
    enum_check(
        "ck_moderation_actions_origin",
        "action_origin",
        "manual",
        "system",
        "automated",
        "ai",
    ),
    enum_check("ck_moderation_actions_scope", "scope_type", "community", "chat"),
    CheckConstraint(
        "expires_at IS NULL OR expires_at > created_at",
        name="ck_moderation_actions_expiry",
    ),
)

Index("ix_moderation_actions_target", moderation_actions.c.target_user_id)
Index("ix_moderation_actions_actor", moderation_actions.c.actor_user_id)
Index("ix_moderation_actions_case", moderation_actions.c.case_id)
Index("ix_moderation_actions_chat", moderation_actions.c.chat_id)
Index("ix_moderation_actions_origin_chat", moderation_actions.c.origin_chat_id)
Index("ix_moderation_actions_status", moderation_actions.c.status)
Index(
    "ix_moderation_actions_type_status",
    moderation_actions.c.action_type,
    moderation_actions.c.status,
)
Index(
    "ix_moderation_actions_target_time",
    moderation_actions.c.target_user_id,
    moderation_actions.c.created_at.desc(),
)
Index("ix_moderation_actions_evidence_upload", moderation_actions.c.evidence_upload_id)
Index("ix_moderation_actions_revoked_by", moderation_actions.c.revoked_by_user_id)
# * One active ban and one active mute per target: a second decision
# * has to supersede the first one instead of duplicating it.
Index(
    "uq_moderation_actions_active_ban",
    moderation_actions.c.target_user_id,
    unique=True,
    postgresql_where=text("action_type = 'ban' AND status = 'active'"),
)
Index(
    "uq_moderation_actions_active_mute",
    moderation_actions.c.target_user_id,
    unique=True,
    postgresql_where=text("action_type = 'mute' AND status = 'active'"),
)

# * An appeal against a ban. Only the banned user can appeal, and the
# * composite foreign key enforces that in the database.
moderation_appeals = Table(
    "moderation_appeals",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("action_id", BigInteger, nullable=False),
    Column("appellant_user_id", BigInteger, nullable=False),
    Column("appeal_text", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column(
        "submitted_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("reviewed_by_user_id", BigInteger, nullable=True),
    Column("decision_note", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["reviewed_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_appeals_reviewed_by",
    ),
    ForeignKeyConstraint(
        ["action_id", "appellant_user_id"],
        ["moderation_actions.id", "moderation_actions.target_user_id"],
        name="fk_moderation_appeals_subject",
    ),
    CheckConstraint("btrim(appeal_text) <> ''", name="ck_moderation_appeals_text"),
    enum_check(
        "ck_moderation_appeals_status",
        "status",
        "pending",
        "accepted",
        "rejected",
        "withdrawn",
    ),
)

Index("ix_moderation_appeals_action", moderation_appeals.c.action_id)
Index("ix_moderation_appeals_status", moderation_appeals.c.status)
Index("ix_moderation_appeals_reviewed_by", moderation_appeals.c.reviewed_by_user_id)
# * One open appeal per action and appellant: a resolved appeal stays
# * in the history, and a new one is a new record.
Index(
    "uq_moderation_appeals_pending",
    moderation_appeals.c.action_id,
    moderation_appeals.c.appellant_user_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)

# * The Telegram messages that belong to a decision: the log, the
# * review card, the appeal notice.
moderation_messages = Table(
    "moderation_messages",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("action_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("message_id", BigInteger, nullable=False),
    Column("message_kind", Text, nullable=False),
    Column("recorded_by_user_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["action_id"],
        ["moderation_actions.id"],
        name="fk_moderation_messages_action",
    ),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_moderation_messages_chat",
    ),
    ForeignKeyConstraint(
        ["recorded_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_messages_recorded_by",
    ),
    enum_check(
        "ck_moderation_messages_kind",
        "message_kind",
        "log",
        "review",
        "appeal_log",
        "notice",
    ),
)

Index("ix_moderation_messages_action", moderation_messages.c.action_id)
Index(
    "ix_moderation_messages_chat",
    moderation_messages.c.chat_id,
    moderation_messages.c.message_id,
)
Index("ix_moderation_messages_recorded_by", moderation_messages.c.recorded_by_user_id)

# * The append-only trail of every decision and state change.
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("actor_user_id", BigInteger, nullable=True),
    Column("subject_user_id", BigInteger, nullable=True),
    Column("event_key", Text, nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=True),
    Column("payload", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "occurred_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("case_id", BigInteger, nullable=True),
    Column("action_id", BigInteger, nullable=True),
    Column("correlation_id", Text, nullable=True),
    Column("operation_id", Text, nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["actor_user_id"],
        ["telegram_users.user_id"],
        name="fk_audit_events_actor",
    ),
    ForeignKeyConstraint(
        ["subject_user_id"],
        ["telegram_users.user_id"],
        name="fk_audit_events_subject",
    ),
    ForeignKeyConstraint(
        ["case_id"],
        ["moderation_cases.id"],
        name="fk_audit_events_case",
    ),
    ForeignKeyConstraint(
        ["action_id"],
        ["moderation_actions.id"],
        name="fk_audit_events_action",
    ),
    CheckConstraint("btrim(event_key) <> ''", name="ck_audit_events_key"),
    enum_check(
        "ck_audit_events_entity_type",
        "entity_type",
        "community_profile",
        "connected_chat",
        "chat_settings",
        "join_request",
        "role_definition",
        "role_assignment",
        "promotion_request",
        "moderation_case",
        "moderation_action",
        "moderation_appeal",
        "evidence_upload",
        "evidence_item",
        "enforcement_run",
        "enforcement_target",
        "automation_policy",
        "automation_run",
        "broadcast_campaign",
        "scheduled_job",
        "scheduled_job_run",
        "telegram_user",
        "retention_policy",
    ),
)

Index("ix_audit_events_occurred", audit_events.c.occurred_at.desc())
Index("ix_audit_events_entity", audit_events.c.entity_type, audit_events.c.entity_id)
Index("ix_audit_events_actor", audit_events.c.actor_user_id)
Index("ix_audit_events_subject", audit_events.c.subject_user_id)
Index("ix_audit_events_case", audit_events.c.case_id)
Index("ix_audit_events_action", audit_events.c.action_id)
Index("ix_audit_events_correlation", audit_events.c.correlation_id)
