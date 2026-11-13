# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Broadcast campaign, target, and attempt tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
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

# * One message the community sends to the managed groups.
broadcast_campaigns = Table(
    "broadcast_campaigns",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column(
        "public_id",
        Text,
        nullable=False,
        server_default=text("gen_random_uuid()::text"),
    ),
    Column("title", Text, nullable=False),
    Column("message_text", Text, nullable=True),
    Column("parse_mode", Text, nullable=True),
    Column("message_payload", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "audience_filter",
        JSONB,
        nullable=False,
        server_default=text('\'{"mode": "all_active"}\'::jsonb'),
    ),
    Column("idempotency_key", Text, nullable=False),
    Column("requested_by_user_id", BigInteger, nullable=True),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("scheduled_at", DateTime(timezone=True), nullable=True),
    Column("target_count", Integer, nullable=False, server_default="0"),
    Column("succeeded_count", Integer, nullable=False, server_default="0"),
    Column("failed_count", Integer, nullable=False, server_default="0"),
    Column("skipped_count", Integer, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["requested_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_broadcast_campaigns_requested_by",
    ),
    UniqueConstraint("public_id", name="uq_broadcast_campaigns_public_id"),
    UniqueConstraint("idempotency_key", name="uq_broadcast_campaigns_idempotency"),
    CheckConstraint("btrim(title) <> ''", name="ck_broadcast_campaigns_title"),
    CheckConstraint(
        "parse_mode IS NULL OR parse_mode IN ('HTML', 'Markdown', 'MarkdownV2')",
        name="ck_broadcast_campaigns_parse_mode",
    ),
    enum_check(
        "ck_broadcast_campaigns_status",
        "status",
        "draft",
        "scheduled",
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "cancelled",
    ),
    CheckConstraint(
        "target_count >= 0 AND succeeded_count >= 0 "
        "AND failed_count >= 0 AND skipped_count >= 0",
        name="ck_broadcast_campaigns_counters",
    ),
    CheckConstraint(
        "btrim(idempotency_key) <> ''", name="ck_broadcast_campaigns_idempotency"
    ),
)

Index("ix_broadcast_campaigns_status", broadcast_campaigns.c.status)
Index("ix_broadcast_campaigns_scheduled", broadcast_campaigns.c.scheduled_at)
Index("ix_broadcast_campaigns_requested_by", broadcast_campaigns.c.requested_by_user_id)

# * One delivery target of one campaign.
broadcast_targets = Table(
    "broadcast_targets",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("campaign_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("telegram_message_id", BigInteger, nullable=True),
    Column("last_error_kind", Text, nullable=True),
    Column("last_error_code", Text, nullable=True),
    Column("last_error_detail", Text, nullable=True),
    Column("response_metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("first_attempt_at", DateTime(timezone=True), nullable=True),
    Column("last_attempt_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["campaign_id"],
        ["broadcast_campaigns.id"],
        name="fk_broadcast_targets_campaign",
    ),
    ForeignKeyConstraint(
        ["chat_id"],
        ["connected_chats.chat_id"],
        name="fk_broadcast_targets_chat",
    ),
    UniqueConstraint(
        "campaign_id", "chat_id", name="uq_broadcast_targets_campaign_chat"
    ),
    enum_check(
        "ck_broadcast_targets_status",
        "status",
        "pending",
        "in_progress",
        "succeeded",
        "failed",
        "skipped",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_broadcast_targets_attempts"),
)

Index("ix_broadcast_targets_campaign", broadcast_targets.c.campaign_id)
Index("ix_broadcast_targets_chat", broadcast_targets.c.chat_id)
Index(
    "ix_broadcast_targets_retry",
    broadcast_targets.c.status,
    broadcast_targets.c.next_retry_at,
)

# * The append-only delivery history of one target.
broadcast_attempts = Table(
    "broadcast_attempts",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("target_id", BigInteger, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("telegram_message_id", BigInteger, nullable=True),
    Column("error_kind", Text, nullable=True),
    Column("error_code", Text, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column(
        "attempted_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("response_metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["target_id"],
        ["broadcast_targets.id"],
        name="fk_broadcast_attempts_target",
    ),
    CheckConstraint("attempt_number > 0", name="ck_broadcast_attempts_number"),
    enum_check(
        "ck_broadcast_attempts_outcome", "outcome", "succeeded", "failed", "skipped"
    ),
)

Index("ix_broadcast_attempts_target", broadcast_attempts.c.target_id)
