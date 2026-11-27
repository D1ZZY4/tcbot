# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Store the public category presentation text with the rule category.

Category labels and the one-line description shown above a category's sections
used to live in the translation catalog. They now belong to the rule set. The
localized presentation is owned by `rule_category_content`, created by revision
0016, which is what the public menu reads. This column is vestigial: no writer
or reader remains in the application, and existing rows keep a NULL value.

Revision ID: 0015_rule_category_description
Revises: 0014_primary_group_enforcement
Create Date: 2026-11-24
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0015_rule_category_description"
down_revision: str | None = "0014_primary_group_enforcement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the optional presentation column where the category catalogue exists."""
    exists = (
        op.get_bind()
        .execute(text("SELECT to_regclass('rule_categories') IS NOT NULL"))
        .scalar()
    )
    if exists:
        op.execute(
            "ALTER TABLE rule_categories ADD COLUMN IF NOT EXISTS description text NULL"
        )


def downgrade() -> None:
    """Drop the presentation column; the stored title remains the label."""
    op.execute("ALTER TABLE rule_categories DROP COLUMN IF EXISTS description")
