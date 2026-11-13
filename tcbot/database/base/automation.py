# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Automation policy, event, run, and step tables."""

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

# * A versioned rule that reacts to normalized events.
automation_policies = Table(
    "automation_policies",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("policy_key", Text, nullable=False),
    Column("scope_type", Text, nullable=False),
    Column("chat_id", BigInteger, nullable=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("is_enabled", Boolean, nullable=False, server_default=text("true")),
    Column("priority", Integer, nullable=False, server_default="100"),
    Column("cooldown_seconds", Integer, nullable=False, server_default="0"),
    Column("max_actions_per_user_per_window", Integer, nullable=True),
    Column("max_actions_window_seconds", Integer, nullable=True),
    Column("created_by_user_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["connected_chats.chat_id"],
        name="fk_automation_policies_chat",
    ),
    ForeignKeyConstraint(
        ["created_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_automation_policies_created_by",
    ),
    UniqueConstraint("policy_key", name="uq_automation_policies_key"),
    CheckConstraint(
        "policy_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_automation_policies_key"
    ),
    enum_check("ck_automation_policies_scope", "scope_type", "community", "chat"),
    CheckConstraint("btrim(name) <> ''", name="ck_automation_policies_name"),
    CheckConstraint(
        "description IS NULL OR btrim(description) <> ''",
        name="ck_automation_policies_description",
    ),
    CheckConstraint("cooldown_seconds >= 0", name="ck_automation_policies_cooldown"),
    CheckConstraint(
        "max_actions_per_user_per_window IS NULL OR max_actions_per_user_per_window > 0",
        name="ck_automation_policies_max_actions",
    ),
    CheckConstraint(
        "(max_actions_per_user_per_window IS NULL) = (max_actions_window_seconds IS NULL)",
        name="ck_automation_policies_limit_pair",
    ),
    CheckConstraint(
        "(scope_type = 'community' AND chat_id IS NULL) "
        "OR (scope_type = 'chat' AND chat_id IS NOT NULL)",
        name="ck_automation_policies_scope_chat",
    ),
)

Index("ix_automation_policies_scope", automation_policies.c.scope_type)
Index("ix_automation_policies_enabled", automation_policies.c.is_enabled)
Index("ix_automation_policies_chat", automation_policies.c.chat_id)
Index("ix_automation_policies_created_by", automation_policies.c.created_by_user_id)

# * One definition of a policy. The published version is immutable.
automation_policy_versions = Table(
    "automation_policy_versions",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("policy_id", BigInteger, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("trigger_definition", JSONB, nullable=False),
    Column("conditions", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("steps_definition", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("change_summary", Text, nullable=True),
    Column("created_by_user_id", BigInteger, nullable=True),
    Column("published_by_user_id", BigInteger, nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("definition_schema_version", Integer, nullable=False, server_default="1"),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["policy_id"],
        ["automation_policies.id"],
        name="fk_automation_policy_versions_policy",
    ),
    ForeignKeyConstraint(
        ["created_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_automation_policy_versions_created_by",
    ),
    ForeignKeyConstraint(
        ["published_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_automation_policy_versions_published_by",
    ),
    UniqueConstraint(
        "policy_id", "version_number", name="uq_automation_policy_versions_number"
    ),
    CheckConstraint("version_number > 0", name="ck_automation_policy_versions_number"),
    CheckConstraint(
        "definition_schema_version > 0", name="ck_automation_policy_versions_schema"
    ),
    enum_check(
        "ck_automation_policy_versions_status",
        "status",
        "draft",
        "published",
        "superseded",
        "archived",
    ),
)

Index("ix_automation_policy_versions_policy", automation_policy_versions.c.policy_id)
Index("ix_automation_policy_versions_status", automation_policy_versions.c.status)
Index(
    "ix_automation_policy_versions_published_by",
    automation_policy_versions.c.published_by_user_id,
)
# * Only one published version per policy.
Index(
    "uq_automation_policy_versions_published",
    automation_policy_versions.c.policy_id,
    unique=True,
    postgresql_where=text("status = 'published'"),
)

# * A normalized input event. The idempotency key keeps one Telegram
# * update from triggering the same policy twice.
automation_events = Table(
    "automation_events",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("subject_user_id", BigInteger, nullable=True),
    Column("context_chat_id", BigInteger, nullable=True),
    Column(
        "occurred_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "received_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("payload", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["subject_user_id"],
        ["telegram_users.user_id"],
        name="fk_automation_events_subject",
    ),
    ForeignKeyConstraint(
        ["context_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_automation_events_context_chat",
    ),
    UniqueConstraint("idempotency_key", name="uq_automation_events_idempotency"),
    CheckConstraint("btrim(event_type) <> ''", name="ck_automation_events_type"),
    enum_check(
        "ck_automation_events_source",
        "source",
        "telegram",
        "manual",
        "system",
        "scheduler",
        "ai",
    ),
    CheckConstraint(
        "btrim(idempotency_key) <> ''", name="ck_automation_events_idempotency"
    ),
)

Index("ix_automation_events_type", automation_events.c.event_type)
Index("ix_automation_events_occurred", automation_events.c.occurred_at.desc())
Index("ix_automation_events_subject", automation_events.c.subject_user_id)
Index("ix_automation_events_context_chat", automation_events.c.context_chat_id)

# * One execution of a policy version against one event.
automation_runs = Table(
    "automation_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column(
        "public_id",
        Text,
        nullable=False,
        server_default=text("gen_random_uuid()::text"),
    ),
    Column("policy_version_id", BigInteger, nullable=False),
    Column("event_id", BigInteger, nullable=False),
    Column("subject_user_id", BigInteger, nullable=True),
    Column("context_chat_id", BigInteger, nullable=True),
    Column("idempotency_key", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("outcome", Text, nullable=True),
    Column("case_id", BigInteger, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_code", Text, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("result", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["policy_version_id"],
        ["automation_policy_versions.id"],
        name="fk_automation_runs_policy_version",
    ),
    ForeignKeyConstraint(
        ["event_id"],
        ["automation_events.id"],
        name="fk_automation_runs_event",
    ),
    ForeignKeyConstraint(
        ["subject_user_id"],
        ["telegram_users.user_id"],
        name="fk_automation_runs_subject",
    ),
    ForeignKeyConstraint(
        ["context_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_automation_runs_context_chat",
    ),
    ForeignKeyConstraint(
        ["case_id"],
        ["moderation_cases.id"],
        name="fk_automation_runs_case",
    ),
    UniqueConstraint("public_id", name="uq_automation_runs_public_id"),
    UniqueConstraint("idempotency_key", name="uq_automation_runs_idempotency"),
    enum_check(
        "ck_automation_runs_status",
        "status",
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "skipped",
        "cancelled",
    ),
    CheckConstraint(
        "btrim(idempotency_key) <> ''", name="ck_automation_runs_idempotency"
    ),
)

Index("ix_automation_runs_status", automation_runs.c.status)
Index("ix_automation_runs_policy_version", automation_runs.c.policy_version_id)
Index("ix_automation_runs_event", automation_runs.c.event_id)
Index("ix_automation_runs_subject", automation_runs.c.subject_user_id)
Index("ix_automation_runs_context_chat", automation_runs.c.context_chat_id)
Index("ix_automation_runs_case", automation_runs.c.case_id)

# * The ordered steps of one run, copied from the published policy.
automation_run_steps = Table(
    "automation_run_steps",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("run_id", BigInteger, nullable=False),
    Column("step_key", Text, nullable=False),
    Column("step_order", Integer, nullable=False),
    Column("step_type", Text, nullable=False),
    Column("config_snapshot", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("moderation_action_id", BigInteger, nullable=True),
    Column("enforcement_run_id", BigInteger, nullable=True),
    Column("error_code", Text, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("output", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["run_id"],
        ["automation_runs.id"],
        name="fk_automation_run_steps_run",
    ),
    ForeignKeyConstraint(
        ["moderation_action_id"],
        ["moderation_actions.id"],
        name="fk_automation_run_steps_moderation_action",
    ),
    ForeignKeyConstraint(
        ["enforcement_run_id"],
        ["moderation_enforcement_runs.id"],
        name="fk_automation_run_steps_enforcement_run",
    ),
    UniqueConstraint("run_id", "step_key", name="uq_automation_run_steps_run_key"),
    CheckConstraint("btrim(step_key) <> ''", name="ck_automation_run_steps_key"),
    CheckConstraint("step_order >= 0", name="ck_automation_run_steps_order"),
    CheckConstraint("attempt_count >= 0", name="ck_automation_run_steps_attempts"),
    enum_check(
        "ck_automation_run_steps_type",
        "step_type",
        "create_case",
        "collect_evidence",
        "warn",
        "mute",
        "ban",
        "kick",
        "notify",
        "request_review",
        "enforce",
        "custom",
    ),
    enum_check(
        "ck_automation_run_steps_status",
        "status",
        "pending",
        "in_progress",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    ),
)

Index("ix_automation_run_steps_run", automation_run_steps.c.run_id)
Index(
    "ix_automation_run_steps_order",
    automation_run_steps.c.run_id,
    automation_run_steps.c.step_order,
)
Index("ix_automation_run_steps_action", automation_run_steps.c.moderation_action_id)
Index("ix_automation_run_steps_enforcement", automation_run_steps.c.enforcement_run_id)

# * The append-only attempt history of one step.
automation_run_step_attempts = Table(
    "automation_run_step_attempts",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("step_id", BigInteger, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
    Column(
        "attempted_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("error_code", Text, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("result", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["step_id"],
        ["automation_run_steps.id"],
        name="fk_automation_run_step_attempts_step",
    ),
    CheckConstraint(
        "attempt_number > 0", name="ck_automation_run_step_attempts_number"
    ),
    enum_check(
        "ck_automation_run_step_attempts_outcome",
        "outcome",
        "completed",
        "failed",
        "skipped",
    ),
)

Index("ix_automation_run_step_attempts_step", automation_run_step_attempts.c.step_id)
