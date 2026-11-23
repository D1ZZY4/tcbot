# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Allow the deployment main group as a durable enforcement target.

The main group is deliberately registered as an inactive connected chat so it
stays out of the federation list. Enforcement still has to reach it: the
queue intentionally inserts a target for the primary group, and the claim and
requeue queries already admit that chat explicitly. The target trigger did
not, so every ban, mute, revoke, and appeal approval rolled back whenever
MAIN_GROUP was configured.

The trigger reads the deployment chat id from the ``tcbot.primary_chat_id``
session GUC published by every application connection. This revision
reapplies the schema functions so an existing deployment picks up the new
predicate.

Revision ID: 0014_primary_group_enforcement
Revises: 0013_role_vocabulary
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0014_primary_group_enforcement"
down_revision: str | None = "0013_role_vocabulary"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reapply the current schema functions in the configured schema."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the refreshed definitions in place.

    The previous function body is not versioned, so there is no safe state to
    restore. Rolling back the application code removes the GUC, and the
    predicate then falls back to active chats only.
    """
