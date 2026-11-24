# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Give rule categories localized presentation rows.

Category labels and descriptions are now rule-set data. One row per category,
set, and locale carries the wording, so an Indonesian reader sees Indonesian
text and an English reader sees English text without a translation catalog.
The application seeds the rows when it creates or seeds a rule set.

Revision ID: 0016_rule_category_content
Revises: 0015_rule_category_description
Create Date: 2026-11-24
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0016_rule_category_content"
down_revision: str | None = "0015_rule_category_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the localized category presentation table."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_category_content (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rule_set_id bigint NOT NULL REFERENCES rule_sets(id),
            category_key text NOT NULL,
            locale text NOT NULL,
            label text NOT NULL CHECK (btrim(label) <> ''),
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_rule_category_content
                UNIQUE (rule_set_id, category_key, locale)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rule_category_content_set "
        "ON rule_category_content (rule_set_id)"
    )


def downgrade() -> None:
    """Drop the localized presentation table and its index."""
    op.execute("DROP INDEX IF EXISTS ix_rule_category_content_set")
    op.execute("DROP TABLE IF EXISTS rule_category_content")
