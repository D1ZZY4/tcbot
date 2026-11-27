# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Apply schema objects that tolerate an older table set.

Early revisions reapply the current SQL files while their own database can
still be missing tables introduced later. The schema loader now filters
CREATE TRIGGER by existing tables, and the policy script skips relations that
do not exist yet. This revision reinstalls those objects on databases already
at the previous head.

Revision ID: 0022_forward_guarded_schema
Revises: 0021_moderation_expiry_clock
Create Date: 2026-11-27
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0022_forward_guarded_schema"
down_revision: str | None = "0021_moderation_expiry_clock"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reinstall schema objects with the forward-reference guards."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the tolerant objects in place; rollback needs an explicit decision."""
