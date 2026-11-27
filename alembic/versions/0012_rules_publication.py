# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Add the rules publication catalogue, slots, and run lock.

Rules gain a category catalogue, one message slot per rendered channel part,
and a short-lived run that serialises a publish plus its channel sync. Item
rows carry a category snapshot so a published version keeps its presentation
when staff rename or reorder categories. The single-draft index prevents two
staff members from opening competing drafts for the same set and locale.

Revision ID: 0012_rules_publication
Revises: 0011_erasure_cleanup
Create Date: 2026-11-21
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op
from tcbot.database.base import metadata
from tcbot.database.schema import apply_schema

revision: str = "0012_rules_publication"
down_revision: str | None = "0011_erasure_cleanup"
branch_labels: str | None = None
depends_on: str | None = None

_NEW_TABLES = ("rule_categories", "rule_publication_runs", "rule_publications")


def upgrade() -> None:
    """Create the new tables, columns, indexes, and the scope trigger."""
    bind = op.get_bind()
    # * The rules feature was later removed. The revision stays in history,
    # * but a fresh chain no longer declares these tables in metadata, so the
    # * original unconditional DDL would fail. Only apply it where the base
    # * tables still exist.
    tables = [metadata.tables[name] for name in _NEW_TABLES if name in metadata.tables]
    if tables:
        metadata.create_all(bind=bind, tables=tables, checkfirst=True)
    exists = bind.execute(text("SELECT to_regclass('rule_items') IS NOT NULL")).scalar()
    if exists:
        op.execute(
            "ALTER TABLE rule_items ADD COLUMN IF NOT EXISTS category_title TEXT"
        )
        op.execute(
            "ALTER TABLE rule_items ADD COLUMN IF NOT EXISTS category_sort_order INTEGER"
        )
    version_exists = bind.execute(
        text("SELECT to_regclass('rule_set_versions') IS NOT NULL")
    ).scalar()
    if version_exists:
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_set_versions_draft "
            "ON rule_set_versions (rule_set_id, locale) WHERE status = 'draft'"
        )
    apply_schema(bind)


def downgrade() -> None:
    """Remove the publication objects while leaving rule content intact."""
    bind = op.get_bind()
    # * A fresh chain never created the rules tables, so IF EXISTS on a trigger
    # * or column is not enough: PostgreSQL still requires the relation itself.
    publication_table = bind.execute(
        text("SELECT to_regclass('rule_publications') IS NOT NULL")
    ).scalar()
    if publication_table:
        op.execute(
            "DROP TRIGGER IF EXISTS trg_validate_rule_publication_scope "
            "ON rule_publications"
        )
    op.execute("DROP FUNCTION IF EXISTS validate_rule_publication_scope() CASCADE")
    op.execute(
        "DELETE FROM retention_policies WHERE target_table IN "
        "('rule_categories', 'rule_publication_runs', 'rule_publications')"
    )
    for name in reversed(_NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    op.execute("DROP INDEX IF EXISTS uq_rule_set_versions_draft")
    if bind.execute(text("SELECT to_regclass('rule_items') IS NOT NULL")).scalar():
        op.execute("ALTER TABLE rule_items DROP COLUMN IF EXISTS category_sort_order")
        op.execute("ALTER TABLE rule_items DROP COLUMN IF EXISTS category_title")
