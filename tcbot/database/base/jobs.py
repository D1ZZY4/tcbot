# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduled job registry, run history, erasure queue, and retention tables."""

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

# * The registry of the background jobs. The schedule is the truth
# * about what runs, the history says whether it worked.
scheduled_jobs = Table(
    "scheduled_jobs",
    metadata,
    Column("job_key", Text, nullable=False),
    Column("job_kind", Text, nullable=False, server_default="maintenance"),
    Column("description", Text, nullable=True),
    Column("schedule_spec", Text, nullable=False),
    Column("is_enabled", Boolean, nullable=False, server_default=text("true")),
    Column("timeout_seconds", Integer, nullable=False, server_default="60"),
    Column("idempotency_scope", Text, nullable=True),
    Column("last_started_at", DateTime(timezone=True), nullable=True),
    Column("last_success_at", DateTime(timezone=True), nullable=True),
    Column("last_status", Text, nullable=False, server_default="pending"),
    Column("last_error", Text, nullable=True),
    Column("consecutive_failures", Integer, nullable=False, server_default="0"),
    Column("last_duration_ms", Integer, nullable=True),
    Column("updated_by_user_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("job_key"),
    ForeignKeyConstraint(
        ["updated_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_scheduled_jobs_updated_by",
    ),
    CheckConstraint("job_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_scheduled_jobs_key"),
    enum_check("ck_scheduled_jobs_kind", "job_kind", "maintenance", "dispatch"),
    CheckConstraint("btrim(schedule_spec) <> ''", name="ck_scheduled_jobs_schedule"),
    CheckConstraint("timeout_seconds > 0", name="ck_scheduled_jobs_timeout"),
    enum_check(
        "ck_scheduled_jobs_last_status",
        "last_status",
        "pending",
        "running",
        "success",
        "failed",
        "skipped",
    ),
    CheckConstraint("consecutive_failures >= 0", name="ck_scheduled_jobs_failures"),
    CheckConstraint(
        "last_duration_ms IS NULL OR last_duration_ms >= 0",
        name="ck_scheduled_jobs_duration",
    ),
)

Index("ix_scheduled_jobs_updated_by", scheduled_jobs.c.updated_by_user_id)

# * The append-only history of one job execution.
scheduled_job_runs = Table(
    "scheduled_job_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("job_key", Text, nullable=False),
    Column("run_key", Text, nullable=False),
    Column("triggered_by", Text, nullable=False, server_default="cron"),
    Column("status", Text, nullable=False, server_default="running"),
    Column(
        "started_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("affected_count", Integer, nullable=True),
    Column("error_kind", Text, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("payload", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["job_key"],
        ["scheduled_jobs.job_key"],
        name="fk_scheduled_job_runs_job",
    ),
    UniqueConstraint("run_key", name="uq_scheduled_job_runs_run_key"),
    enum_check(
        "ck_scheduled_job_runs_trigger", "triggered_by", "cron", "manual", "app"
    ),
    enum_check(
        "ck_scheduled_job_runs_status",
        "status",
        "running",
        "success",
        "failed",
        "skipped",
    ),
    CheckConstraint(
        "duration_ms IS NULL OR duration_ms >= 0", name="ck_scheduled_job_runs_duration"
    ),
)

Index("ix_scheduled_job_runs_job", scheduled_job_runs.c.job_key)
Index("ix_scheduled_job_runs_started", scheduled_job_runs.c.started_at.desc())

# * The queue of accounts the user deleted on Telegram. The profile is
# * anonymized, the history stays readable.
telegram_user_erasures = Table(
    "telegram_user_erasures",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("source", Text, nullable=False, server_default="operator"),
    Column("status", Text, nullable=False, server_default="pending"),
    Column(
        "requested_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("processed_at", DateTime(timezone=True), nullable=True),
    Column("processed_by_user_id", BigInteger, nullable=True),
    Column("affected", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column("notes", Text, nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["user_id"],
        ["telegram_users.user_id"],
        name="fk_telegram_user_erasures_user",
    ),
    ForeignKeyConstraint(
        ["processed_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_telegram_user_erasures_processed_by",
    ),
    CheckConstraint("btrim(reason) <> ''", name="ck_telegram_user_erasures_reason"),
    enum_check(
        "ck_telegram_user_erasures_source",
        "source",
        "telegram_report",
        "user_request",
        "operator",
        "sweep",
    ),
    enum_check(
        "ck_telegram_user_erasures_status",
        "status",
        "pending",
        "processing",
        "completed",
        "retained",
    ),
)

Index("ix_telegram_user_erasures_status", telegram_user_erasures.c.status)
Index(
    "ix_telegram_user_erasures_processed_by",
    telegram_user_erasures.c.processed_by_user_id,
)
# * One open request per user: a second report joins the open one.
Index(
    "uq_telegram_user_erasures_open",
    telegram_user_erasures.c.user_id,
    unique=True,
    postgresql_where=text("status IN ('pending', 'processing')"),
)

# * The retention contract per table. A null window keeps the data.
retention_policies = Table(
    "retention_policies",
    metadata,
    Column("target_table", Text, nullable=False),
    Column("data_class", Text, nullable=False, server_default="reference"),
    Column("retention_days", Integer, nullable=True),
    Column("time_column", Text, nullable=True),
    Column("is_enabled", Boolean, nullable=False, server_default=text("true")),
    Column("rationale", Text, nullable=True),
    Column("last_run_at", DateTime(timezone=True), nullable=True),
    Column("last_removed", Integer, nullable=False, server_default="0"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("target_table"),
    enum_check(
        "ck_retention_policies_data_class",
        "data_class",
        "history",
        "telemetry",
        "identity_cache",
        "runtime_state",
        "reference",
    ),
    CheckConstraint(
        "retention_days IS NULL OR retention_days > 0",
        name="ck_retention_policies_days",
    ),
    CheckConstraint("last_removed >= 0", name="ck_retention_policies_removed"),
)
