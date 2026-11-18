# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reapply the erasure cleanup after it learned to close open decisions.

The erasure function now refuses the current owner, withdraws pending
appeals and review slots, cancels pending promotion requests, and reports
the real count of revoked moderation actions. Those definitions live in
the schema SQL files, so an existing database needs this revision to
re-read them.

Revision ID: 0011_erasure_cleanup
Revises: 0010_schema_hardening
Create Date: 2026-11-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0011_erasure_cleanup"
down_revision: str | None = "0010_schema_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reapply the current definition of every schema object."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the objects in place; the previous function body is not versioned."""
