# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member cache sort indexes.

Revision ID: 0002
Revises: 0001_initial
Create Date: 2026-11-12

The name-search indexes use ``text_pattern_ops``, which only provides the
pattern comparison operators. The paged user list sorts on the same
columns, and without a default-opclass index the planner sorts the whole
member cache on every page turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0002"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the two default-opclass sort indexes."""
    op.create_index(
        "ix_member_cache_first_name_lower_sort",
        "member_cache",
        ["first_name_lower", "user_id"],
        unique=False,
    )
    op.create_index(
        "ix_member_cache_username_lower_sort",
        "member_cache",
        ["username_lower", "user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the two default-opclass sort indexes."""
    op.drop_index("ix_member_cache_username_lower_sort", table_name="member_cache")
    op.drop_index("ix_member_cache_first_name_lower_sort", table_name="member_cache")
