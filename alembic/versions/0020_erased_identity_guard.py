# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Keep an erased profile from being repopulated by ordinary identity harvests.

Erasure clears the profile but keeps the identity row for history. Every later
update harvests the acting user's name and username, so the row was silently
repopulated and a second erasure was refused forever. This revision installs
the database guard and permits a repeat erasure to clean up affected rows.

Revision ID: 0020_erased_identity_guard
Revises: 0019_schema_hardening_reapply
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0020_erased_identity_guard"
down_revision: str | None = "0019_schema_hardening_reapply"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Install the guard function, its trigger, and the permissive request body."""
    apply_schema(op.get_bind())


def downgrade() -> None:
    """Leave the guard in place; rollback needs an explicit operator decision."""
