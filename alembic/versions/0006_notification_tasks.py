# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Add the durable review-card edit outbox.

A card edit that fails in the handler is retried by the scheduler instead
of leaving a settled appeal with a live-looking card. Revision 0003
creates its tables from the current metadata, so this revision only adds
the table when the database predates it.

Revision ID: 0006_notification_tasks
Revises: 0005_promotion_request_expiry
Create Date: 2026-11-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from tcbot.database.base import metadata, moderation_notification_tasks
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0006_notification_tasks"
down_revision: str | None = "0005_promotion_request_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the outbox table and reapply the SQL objects."""
    bind = op.get_bind()
    metadata.create_all(
        bind,
        tables=[moderation_notification_tasks],
        checkfirst=True,
    )
    # ! CRITICAL: the schema files are current, not the schema of this
    # ! revision. The registry seed already names job_owner, which revision
    # ! 0007 adds, so an existing database that stops at 0005 would fail
    # ! here before reaching 0007. Add the column when it is missing; 0007
    # ! still owns its check constraint and reapplies the schema.
    op.execute(
        "ALTER TABLE scheduled_jobs "
        "ADD COLUMN IF NOT EXISTS job_owner TEXT NOT NULL DEFAULT 'application'"
    )
    # * The new table is in the policy list and the retention seed, and the
    # * promotion lifecycle guard changed in revision 0005. Reapplying the
    # * schema objects here covers both on an existing database.
    apply_schema(bind)


def downgrade() -> None:
    """Drop the outbox table and its retention policy."""
    # * The upgrade seeds a retention policy for this table. Leaving it behind
    # * makes the daily sweep delete from a table that no longer exists and
    # * aborts the whole retention run.
    op.execute(
        "DELETE FROM retention_policies "
        "WHERE target_table = 'moderation_notification_tasks'"
    )
    moderation_notification_tasks.drop(op.get_bind(), checkfirst=True)
