# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Include the primary group in community-scoped reconcile runs.

``enqueue_reconcile_run`` previously selected only ``connected_chats.is_active``,
omitting the deployment main group (which is registered inactive on purpose).
This revision reapplies the schema functions so reconcile runs target the
primary group alongside active connected chats.

Revision ID: 0022_reconcile_primary_chat
Revises: 0021_moderation_expiry_clock
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0022_reconcile_primary_chat"
down_revision: str | None = "0021_moderation_expiry_clock"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reinstall the schema objects with the updated reconcile target predicate."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the refreshed function definitions in place."""
