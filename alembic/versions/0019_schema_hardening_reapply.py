# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply schema objects with the promotion rejection and RLS fixes.

Promotion rejection wrote the public short request id into an audit entity
that the guard validates as a numeric primary key, so every rejection rolled
back. Two SECURITY DEFINER functions also had a malformed quoted search path.
Localized rule-category content was missing from the RLS and retention
inventories. Reapplying the schema delivers all three to an existing database.

Revision ID: 0019_schema_hardening_reapply
Revises: 0018_community_primary_chat
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0019_schema_hardening_reapply"
down_revision: str | None = "0018_community_primary_chat"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reapply the current schema objects in the configured schema."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the hardened function definitions in place."""
