# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Align moderation expiry with the database transaction clock.

The insert trigger expired a prior timed action by comparing its deadline with
the application's ``created_at``, while the update guard compares that deadline
with PostgreSQL's ``now()``. A leading application clock made the two
predicates disagree, so a new ban or mute filed as a prior timed action lapsed
was rejected in full. This revision reinstalls the schema with the insert
trigger using the same database clock as the guard.

Revision ID: 0021_moderation_expiry_clock
Revises: 0020_erased_identity_guard
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0021_moderation_expiry_clock"
down_revision: str | None = "0020_erased_identity_guard"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reinstall the schema objects with the corrected expiry predicate."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the corrected function in place; rollback needs an explicit decision."""
