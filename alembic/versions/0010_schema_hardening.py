# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply the schema objects after the definer paths and erasure order changed.

Six SECURITY DEFINER functions pinned ``public`` into their search path
instead of the schema the files are applied to, and the erasure batch read
its rows by timestamp alone. The functions, triggers, views, policies, and
reference data live in SQL files, so a deployment already at revision 0009
never re-reads them. This revision reapplies the files.

Revision ID: 0010_schema_hardening
Revises: 0009_reapply_reconcile_window
Create Date: 2026-11-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0010_schema_hardening"
down_revision: str | None = "0009_reapply_reconcile_window"
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
