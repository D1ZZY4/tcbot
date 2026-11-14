# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply the schema objects after the function body changed.

The functions, the triggers, the views, the policies, and the reference
data live in SQL files, and a deployment that already ran revision 0003
never re-reads them. This revision reapplies the files so a changed
function body reaches every existing database without a hand-run dump.

Revision ID: 0004_reapply_schema_objects
Revises: 0003_community_schema
Create Date: 2026-11-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0004_reapply_schema_objects"
down_revision: str | None = "0003_community_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reapply the current definition of every schema object."""
    bind = op.get_bind()
    # * Revision 0003 may have left deferred trigger events pending on the
    # * imported rows. PostgreSQL refuses ALTER TABLE ... ENABLE ROW LEVEL
    # * SECURITY while a trigger event is still queued for the table, so the
    # * events are materialised before the policies are reapplied.
    bind.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    apply_schema(bind)


def downgrade() -> None:
    """Leave the objects in place.

    The revision only refreshes definitions; the previous function body is
    not versioned, so there is nothing safe to restore.
    """
