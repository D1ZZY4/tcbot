# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Remove the community rules feature and its moderation linkage.

The application no longer owns rule sets, publications, acknowledgements, or
the case-to-rule link. This revision removes the schema objects and the seeded
permissions and retention rows so a fresh boot cannot recreate them.

Revision ID: 0023_remove_rules_feature
Revises: 0022_forward_guarded_schema
Create Date: 2026-11-28
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision: str = "0023_remove_rules_feature"
down_revision: str | None = "0022_forward_guarded_schema"
branch_labels: str | None = None
depends_on: str | None = None

_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("trg_ensure_published_rule_acknowledgement", "rule_acknowledgements"),
    ("trg_guard_rule_item_draft_only", "rule_items"),
    ("trg_guard_rule_set_version_changes", "rule_set_versions"),
    ("trg_rule_acknowledgements_append_only", "rule_acknowledgements"),
    ("trg_rule_set_versions_set_updated_at", "rule_set_versions"),
    ("trg_rule_sets_guard_identity", "rule_sets"),
    ("trg_rule_sets_prevent_delete", "rule_sets"),
    ("trg_rule_sets_prevent_truncate", "rule_sets"),
    ("trg_rule_sets_set_updated_at", "rule_sets"),
    ("trg_validate_moderation_case_rule_scope", "moderation_case_rules"),
    ("trg_validate_rule_publication_scope", "rule_publications"),
)

_FUNCTIONS: tuple[str, ...] = (
    "ensure_published_rule_acknowledgement",
    "guard_rule_acknowledgement_history",
    "guard_rule_item_draft_only",
    "guard_rule_set_identity",
    "guard_rule_set_version_changes",
    "validate_moderation_case_rule_scope",
    "validate_rule_publication_scope",
)

# * Drop order respects the foreign keys: children before parents, and the
# * case-to-rule link before rule_items.
_TABLES: tuple[str, ...] = (
    "rule_acknowledgements",
    "rule_publications",
    "rule_publication_runs",
    "rule_category_content",
    "rule_categories",
    "moderation_case_rules",
    "rule_items",
    "rule_set_versions",
    "rule_sets",
)

_REMOVED_TABLES: tuple[str, ...] = (
    "moderation_case_rules",
    "rule_acknowledgements",
    "rule_categories",
    "rule_category_content",
    "rule_items",
    "rule_publication_runs",
    "rule_publications",
    "rule_set_versions",
    "rule_sets",
)


def upgrade() -> None:
    """Drop rules schema objects, permissions, and retention rows."""
    bind = op.get_bind()
    for name, table in _TRIGGERS:
        exists = bind.execute(
            text("SELECT to_regclass(:name) IS NOT NULL").bindparams(name=table)
        ).scalar()
        if exists:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    for name in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {name}() CASCADE")
    # * All values are module constants, so literal lists are safe and avoid
    # * expanding bind parameters that differ across SQLAlchemy versions.
    tables = ", ".join(f"'{name}'" for name in _REMOVED_TABLES)
    op.execute(f"DELETE FROM retention_policies WHERE target_table IN ({tables})")
    op.execute(
        "DELETE FROM role_permissions "
        "WHERE permission_key IN ('rules.manage', 'rules.view')"
    )
    op.execute(
        "DELETE FROM permission_definitions "
        "WHERE permission_key IN ('rules.manage', 'rules.view')"
    )
    for name in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {name}")


def downgrade() -> None:
    """Refuse: destroying rule content is not reversible from an empty schema."""
    raise RuntimeError(
        "The rules feature was removed; restore rule data from a backup "
        "before rolling back this revision."
    )
