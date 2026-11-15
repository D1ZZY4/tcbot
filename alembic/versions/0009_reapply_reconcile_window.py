# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply the schema objects after the stale-target window changed.

The pg_cron reconciliation reads the schema functions from SQL files, and a
deployment at revision 0008 never re-reads them. The reconciliation now
falls back to the target update moment when no attempt was recorded, so an
existing database needs the new function body before its scheduled job can
recover a worker that died after claiming a target.

Revision ID: 0009_reapply_reconcile_window
Revises: 0008_kick_failed_status
Create Date: 2026-11-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0009_reapply_reconcile_window"
down_revision: str | None = "0008_kick_failed_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reapply the current definition of every schema object."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the objects in place.

    The revision only refreshes definitions; the previous function body is
    not versioned, so there is nothing safe to restore.
    """
