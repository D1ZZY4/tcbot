# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply schema objects after the rules feature was removed.

Revision 0023 dropped the rules tables and functions but did not reinstall the
current SQL files. A deployment upgrading from 0022 therefore kept the older
``repoint_chat_records`` body, which updated ``moderation_case_rules``. That
function fails after the table is gone. This revision reapplies the schema
objects; the loader replaces functions and views, filters triggers by existing
tables, and skips policies for missing relations, so it is safe after the drop.

Revision ID: 0024_reapply_schema
Revises: 0023_remove_rules_feature
Create Date: 2026-11-28
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0024_reapply_schema"
down_revision: str | None = "0023_remove_rules_feature"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reinstall the current views, functions, triggers, policies, and seed data."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the reapplied objects in place; rollback needs an explicit decision."""
