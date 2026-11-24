# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Add the stored primary chat id to community settings.

The primary-group trigger falls back to this column when the session setting is
absent. The column was added to the declared schema and to the trigger bodies
without a revision, so an existing deployment upgrading to 0017 kept a table
without it and every chat-scoped moderation write failed at the trigger.

Revision ID: 0018_community_primary_chat
Revises: 0017_primary_chat_predicate
Create Date: 2026-11-24
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0018_community_primary_chat"
down_revision: str | None = "0017_primary_chat_predicate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable primary chat id column."""
    op.execute(
        "ALTER TABLE community_settings ADD COLUMN IF NOT EXISTS primary_chat_id bigint NULL"
    )


def downgrade() -> None:
    """Leave the column in place.

    The trigger functions installed by 0017 still read it, so dropping the
    column here would break chat-scoped moderation after a rollback.
    """
