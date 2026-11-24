# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply schema functions after the primary-chat predicate widened.

Chat-scoped decisions in the deployment main group were rejected because the
action trigger required an active connected chat. The main group is registered
inactive on purpose, so the trigger now admits the chat named by the session
setting, matching the enforcement target trigger.

Revision ID: 0017_primary_chat_predicate
Revises: 0016_rule_category_content
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0017_primary_chat_predicate"
down_revision: str | None = "0016_rule_category_content"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reapply the current schema functions in the configured schema."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the refreshed function definitions in place."""
