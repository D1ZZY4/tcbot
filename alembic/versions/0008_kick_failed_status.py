# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Record a kick that did not complete its ban or rejoin step.

A kick is audited before enforcement, so its row starts ``completed``. When
the ban or the follow-up unban fails, the row had no status that described
the outcome. ``failed`` separates a delivered kick from one that never
happened, and the guard accepts the transition back to ``completed`` when
the durable unban repair lands.

Revision ID: 0008_kick_failed_status
Revises: 0007_scheduled_job_owner
Create Date: 2026-11-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection

revision: str = "0008_kick_failed_status"
down_revision: str | None = "0007_scheduled_job_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE: str = "moderation_actions"
_STATUS_CHECK: str = "ck_moderation_actions_status"
_STATUS_EXPRESSION: str = (
    "status IN ('active', 'completed', 'revoked', 'expired', 'superseded', 'failed')"
)
_STATUS_EXPRESSION_PREVIOUS: str = (
    "status IN ('active', 'completed', 'revoked', 'expired', 'superseded')"
)


def _check_names(bind: Connection) -> set[str]:
    """Return the check constraints the table currently carries."""
    names: set[str] = set()
    for check in sa.inspect(bind).get_check_constraints(_TABLE):
        name = check.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def upgrade() -> None:
    """Allow ``failed`` for a kick and reapply the transition guard."""
    bind = op.get_bind()
    if _STATUS_CHECK in _check_names(bind):
        op.drop_constraint(_STATUS_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_STATUS_CHECK, _TABLE, _STATUS_EXPRESSION)
    # * The update guard is the other half of the contract: it has to accept
    # * completed -> failed -> completed for a kick and nothing else.
    apply_schema(bind)


def downgrade() -> None:
    """Fold failed kicks back into completed and restore the narrower check."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE moderation_actions SET status = 'completed' WHERE status = 'failed'"
        )
    )
    if _STATUS_CHECK in _check_names(bind):
        op.drop_constraint(_STATUS_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_STATUS_CHECK, _TABLE, _STATUS_EXPRESSION_PREVIOUS)
