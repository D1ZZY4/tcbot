# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Normalise the role vocabulary to owner, admin, developer, moderator.

The community schema already names its roles owner, admin, developer, and
moderator, but an older deployment can still carry founder and tester rows in
assignments, promotion requests, and permission grants. This revision maps
every stored row to the final vocabulary, resolving an active duplicate in
favour of the final role before renaming, and removes the two stale
definitions. The change is one way: downgrade does not reintroduce the old
names. Take a database backup before upgrading a deployment that still stores
founder or tester values, since those values cannot be reconstructed from the
final vocabulary.

Revision ID: 0013_role_vocabulary
Revises: 0012_rules_publication
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op
from tcbot.database.schema import apply_schema

revision: str = "0013_role_vocabulary"
down_revision: str | None = "0012_rules_publication"
branch_labels: str | None = None
depends_on: str | None = None

# * The guards reinstalled below reject exactly the facts this revision must
# * rewrite: an immutable role key, an immutable requested role, and the
# * deletion of a system role definition. Alembic runs the revision in one
# * transaction, so disabling these user triggers is rolled back with the
# * migration on any failure; no other trigger on these tables is touched.
_MIGRATION_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("promotion_requests", "trg_promotion_requests_lifecycle"),
    ("role_assignments", "trg_role_assignments_guard_update"),
    ("role_definitions", "trg_role_definitions_guard_system"),
)

_FINAL_ROLES = (
    (
        "owner",
        "Owner",
        100,
        "Single owner of the community with full administrative control.",
    ),
    (
        "admin",
        "Admin",
        80,
        "Community administrator responsible for staff, moderation, groups, rules, and operations.",
    ),
    (
        "developer",
        "Developer",
        60,
        "Technical and operational staff role for development, diagnostics, and approved moderation tasks.",
    ),
    (
        "moderator",
        "Moderator",
        40,
        "Community moderator handling day-to-day moderation tasks and group-level actions.",
    ),
)


def upgrade() -> None:
    """Normalise every stored role reference and remove the stale names."""
    # * Reinstall the schema objects first: a deployment already at 0012 still
    # * carries the old guard whose BEFORE DELETE trigger returned NULL and
    # * silently suppressed the stale-definition deletes below.
    apply_schema(op.get_bind())
    for table, trigger in _MIGRATION_TRIGGERS:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")

    for key, display, priority, description in _FINAL_ROLES:
        op.execute(
            "INSERT INTO role_definitions (role_key, display_name, priority, "
            "is_system, description) VALUES "
            f"('{key}', '{display}', {priority}, TRUE, '{description}') "
            "ON CONFLICT (role_key) DO UPDATE SET display_name = EXCLUDED.display_name, "
            "priority = EXCLUDED.priority, is_system = TRUE, "
            "description = EXCLUDED.description"
        )

    # * A user holding both the old and the final role actively would violate
    # * the one-active-role index on the rename, so revoke the old row first.
    for old, final in (("founder", "owner"), ("tester", "moderator")):
        op.execute(
            "UPDATE role_assignments AS old SET status = 'revoked', "
            "revoked_at = now() WHERE old.role_key = '" + old + "' "
            "AND old.status = 'active' AND EXISTS ("
            "SELECT 1 FROM role_assignments AS final WHERE final.user_id = old.user_id "
            "AND final.role_key = '" + final + "' AND final.status = 'active')"
        )
        op.execute(
            "UPDATE role_assignments SET role_key = '" + final + "' "
            "WHERE role_key = '" + old + "'"
        )
        op.execute(
            "UPDATE promotion_requests SET requested_role_key = '" + final + "' "
            "WHERE requested_role_key = '" + old + "'"
        )
        op.execute(
            "INSERT INTO role_permissions (role_key, permission_key) "
            "SELECT '" + final + "', permission_key FROM role_permissions "
            "WHERE role_key = '" + old + "' ON CONFLICT DO NOTHING"
        )
        op.execute("DELETE FROM role_permissions WHERE role_key = '" + old + "'")
        op.execute("DELETE FROM role_definitions WHERE role_key = '" + old + "'")

    op.execute(
        "DO $check$ BEGIN IF EXISTS ("
        "SELECT 1 FROM role_definitions WHERE role_key IN ('founder', 'tester')"
        " UNION ALL SELECT 1 FROM role_assignments "
        "WHERE role_key IN ('founder', 'tester')"
        " UNION ALL SELECT 1 FROM role_permissions "
        "WHERE role_key IN ('founder', 'tester')"
        " UNION ALL SELECT 1 FROM promotion_requests "
        "WHERE requested_role_key IN ('founder', 'tester')"
        ") THEN RAISE EXCEPTION 'Legacy role vocabulary remains after 0013'; "
        "END IF; END $check$"
    )

    for table, trigger in _MIGRATION_TRIGGERS:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


def downgrade() -> None:
    """Leave the final vocabulary in place; the old names are not restored."""
