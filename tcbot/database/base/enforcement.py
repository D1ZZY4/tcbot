# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement run, target, and attempt tables."""

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
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, enum_check, metadata

# * One operation that applies, revokes, or reconciles one decision
# * across the managed groups.
moderation_enforcement_runs = Table(
    "moderation_enforcement_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("action_id", BigInteger, nullable=False),
    Column("operation", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("requested_by_user_id", BigInteger, nullable=True),
    Column("status", Text, nullable=False, server_default="queued"),
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
    Column("scheduled_job_run_id", BigInteger, nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["action_id"],
        ["moderation_actions.id"],
        name="fk_moderation_enforcement_runs_action",
    ),
    ForeignKeyConstraint(
        ["requested_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_moderation_enforcement_runs_requested_by",
    ),
    ForeignKeyConstraint(
        ["scheduled_job_run_id"],
        ["scheduled_job_runs.id"],
        name="fk_moderation_enforcement_runs_job_run",
    ),
    UniqueConstraint(
        "idempotency_key", name="uq_moderation_enforcement_runs_idempotency"
    ),
    enum_check(
        "ck_moderation_enforcement_runs_operation",
        "operation",
        "apply",
        "revoke",
        "reconcile",
    ),
    enum_check(
        "ck_moderation_enforcement_runs_status",
        "status",
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
        name="ck_moderation_enforcement_runs_counters",
    ),
    CheckConstraint(
        "btrim(idempotency_key) <> ''",
        name="ck_moderation_enforcement_runs_idempotency",
    ),
)

Index("ix_moderation_enforcement_runs_action", moderation_enforcement_runs.c.action_id)
Index("ix_moderation_enforcement_runs_status", moderation_enforcement_runs.c.status)
Index(
    "ix_moderation_enforcement_runs_job_run",
    moderation_enforcement_runs.c.scheduled_job_run_id,
)
Index(
    "ix_moderation_enforcement_runs_requested_by",
    moderation_enforcement_runs.c.requested_by_user_id,
)

# * The per-group result of one enforcement run.
moderation_enforcement_targets = Table(
    "moderation_enforcement_targets",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("run_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_error_kind", Text, nullable=True),
    Column("last_error_code", Text, nullable=True),
    Column("last_error_detail", Text, nullable=True),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("first_attempt_at", DateTime(timezone=True), nullable=True),
    Column("last_attempt_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("response_metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["run_id"],
        ["moderation_enforcement_runs.id"],
        name="fk_moderation_enforcement_targets_run",
    ),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_moderation_enforcement_targets_chat",
    ),
    UniqueConstraint(
        "run_id", "chat_id", name="uq_moderation_enforcement_targets_run_chat"
    ),
    enum_check(
        "ck_moderation_enforcement_targets_status",
        "status",
        "pending",
        "in_progress",
        "succeeded",
        "skipped",
        "failed",
    ),
    CheckConstraint(
        "attempt_count >= 0", name="ck_moderation_enforcement_targets_attempts"
    ),
)

Index("ix_moderation_enforcement_targets_run", moderation_enforcement_targets.c.run_id)
Index(
    "ix_moderation_enforcement_targets_chat", moderation_enforcement_targets.c.chat_id
)
Index(
    "ix_moderation_enforcement_targets_retry",
    moderation_enforcement_targets.c.status,
    moderation_enforcement_targets.c.next_retry_at,
)

# * Every attempt against one target. The history is append-only.
moderation_enforcement_attempts = Table(
    "moderation_enforcement_attempts",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("target_id", BigInteger, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
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
        ["moderation_enforcement_targets.id"],
        name="fk_moderation_enforcement_attempts_target",
    ),
    CheckConstraint(
        "attempt_number > 0", name="ck_moderation_enforcement_attempts_number"
    ),
    enum_check(
        "ck_moderation_enforcement_attempts_outcome",
        "outcome",
        "succeeded",
        "skipped",
        "failed",
    ),
)

Index(
    "ix_moderation_enforcement_attempts_target",
    moderation_enforcement_attempts.c.target_id,
)
