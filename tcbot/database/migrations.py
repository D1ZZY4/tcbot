# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Alembic wiring and schema-compatibility checks for TCF Bot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from tcbot.database.base import metadata

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig
    from sqlalchemy.engine import Connection

# * The repository root holds ``alembic.ini`` and the ``alembic/`` script
# * directory. The package lives two levels below it.
_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _ROOT / "alembic.ini"

# * These relations belong to the normalized Transsion Core schema, not the
# * legacy schema this application currently declares in base.py. A marker is
# * enough to refuse an accidental cross-generation migration before Alembic
# * can create, alter, or collide with application objects.
_NORMALIZED_SCHEMA_MARKERS: frozenset[str] = frozenset(
    {
        "audit_events",
        "chat_members",
        "chat_settings",
        "federation_groups",
        "federation_settings",
        "federations",
        "join_requests",
        "moderation_actions",
        "moderation_appeals",
        "moderation_case_rules",
        "moderation_cases",
        "moderation_evidence_items",
        "moderation_evidence_uploads",
        "moderation_messages",
        "permission_definitions",
        "role_assignments",
        "role_definitions",
        "role_permissions",
        "rule_acknowledgements",
        "rule_items",
        "rule_set_versions",
        "rule_sets",
        "telegram_chats",
        "telegram_users",
    }
)
_LEGACY_APPLICATION_RELATIONS: frozenset[str] = frozenset(metadata.tables)


def validate_schema_relations(relations: set[str]) -> None:
    """Reject a database that is not managed by this legacy Alembic history.

    The normalized Transsion Core schema is a separate data model and has a
    separate migration history. This bot release must never baseline or
    upgrade that schema using its legacy Alembic revisions.
    """
    normalized = sorted(_NORMALIZED_SCHEMA_MARKERS.intersection(relations))
    if normalized:
        names = ", ".join(normalized)
        raise RuntimeError(
            "Refusing to run the legacy TCBot Alembic migrations against a "
            "normalized Transsion Core schema. Detected schema markers: "
            f"{names}. This application release still expects the legacy "
            "schema declared in tcbot.database.base. No migration was run."
        )

    unversioned = sorted(_LEGACY_APPLICATION_RELATIONS.intersection(relations))
    if unversioned and "alembic_version" not in relations:
        names = ", ".join(unversioned)
        raise RuntimeError(
            "Refusing to baseline an unversioned database containing existing "
            f"TCBot application relations: {names}. Restore the matching "
            "Alembic history or use the explicit schema cutover procedure. "
            "No migration was run."
        )


def validate_database_schema(connection: Connection) -> None:
    """Validate the current schema before any online Alembic migration."""
    inspector = inspect(connection)
    relations = set(inspector.get_table_names())
    relations.update(inspector.get_view_names())
    validate_schema_relations(relations)



_NORMALIZED_REQUIRED_TABLES: frozenset[str] = frozenset(
    {
        "audit_events",
        "chat_members",
        "chat_settings",
        "federation_groups",
        "federation_settings",
        "federations",
        "join_requests",
        "moderation_actions",
        "moderation_appeals",
        "moderation_case_rules",
        "moderation_cases",
        "moderation_evidence_items",
        "moderation_evidence_uploads",
        "moderation_messages",
        "permission_definitions",
        "role_assignments",
        "role_definitions",
        "role_permissions",
        "rule_acknowledgements",
        "rule_items",
        "rule_set_versions",
        "rule_sets",
        "telegram_chats",
        "telegram_users",
        "user_settings",
        "apscheduler_jobs",
        "mtproto_state",
    }
)
_NORMALIZED_REQUIRED_VIEWS: frozenset[str] = frozenset(
    {"active_bans", "active_mutes", "warn_counts"}
)
_NORMALIZED_REQUIRED_ROLES: frozenset[str] = frozenset(
    {"owner", "admin", "developer", "moderator"}
)


def validate_normalized_schema(connection: Connection, federation_slug: str) -> None:
    """Validate the pre-migrated normalized schema without changing it.

    The normalized schema is managed outside Alembic. Startup therefore checks
    the full runtime contract, security posture, and federation seed row but
    never creates, alters, or repairs database objects.
    """
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema="public"))
    views = set(inspector.get_view_names(schema="public"))
    missing_tables = sorted(_NORMALIZED_REQUIRED_TABLES - tables)
    missing_views = sorted(_NORMALIZED_REQUIRED_VIEWS - views)
    if missing_tables or missing_views:
        missing = [*(f"table:{name}" for name in missing_tables)]
        missing.extend(f"view:{name}" for name in missing_views)
        raise RuntimeError(
            "Normalized database schema is incomplete. Missing "
            + ", ".join(missing)
            + ". Apply the reviewed Supabase migrations before starting TCBot."
        )

    required_columns = {
        "federations": {"id", "slug"},
        "telegram_users": {"user_id", "is_bot"},
        "role_definitions": {"role_key", "priority"},
        "role_assignments": {
            "federation_id",
            "user_id",
            "role_key",
            "assigned_by_user_id",
            "assigned_at",
            "status",
            "expires_at",
            "revoked_at",
            "revoked_by_user_id",
        },
        "permission_definitions": {"permission_key", "resource"},
        "role_permissions": {"role_key", "permission_key"},
        "apscheduler_jobs": {"id", "next_run_time", "job_state"},
        "mtproto_state": {"id", "value", "owner", "expires_at"},
    }
    missing_columns: list[str] = []
    for table_name, expected in required_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table_name, schema="public")}
        missing_columns.extend(
            f"public.{table_name}.{column}" for column in sorted(expected - actual)
        )
    if missing_columns:
        raise RuntimeError(
            "Normalized database schema is missing required columns: "
            + ", ".join(missing_columns)
        )

    row = connection.execute(
        text(
            "SELECT id FROM public.federations "
            "WHERE slug = :slug AND status = 'active' LIMIT 2"
        ),
        {"slug": federation_slug},
    ).fetchall()
    if len(row) != 1:
        raise RuntimeError(
            "Normalized database must contain exactly one active federation "
            f"with slug {federation_slug!r}."
        )

    role_rows = connection.execute(
        text(
            "SELECT role_key FROM public.role_definitions "
            "WHERE role_key IN (:owner, :admin, :developer, :moderator)"
        ),
        {
            "owner": "owner",
            "admin": "admin",
            "developer": "developer",
            "moderator": "moderator",
        },
    ).scalars().all()
    missing_roles = sorted(_NORMALIZED_REQUIRED_ROLES - set(role_rows))
    if missing_roles:
        raise RuntimeError(
            "Normalized database is missing required system roles: "
            + ", ".join(missing_roles)
        )

    security = connection.execute(
        text(
            """
            SELECT
                count(*) FILTER (
                    WHERE c.relkind = 'r' AND NOT c.relrowsecurity
                ) AS rls_disabled,
                count(*) FILTER (
                    WHERE has_table_privilege('anon', c.oid, 'SELECT')
                       OR has_table_privilege('anon', c.oid, 'INSERT')
                       OR has_table_privilege('anon', c.oid, 'UPDATE')
                       OR has_table_privilege('anon', c.oid, 'DELETE')
                       OR has_table_privilege('authenticated', c.oid, 'SELECT')
                       OR has_table_privilege('authenticated', c.oid, 'INSERT')
                       OR has_table_privilege('authenticated', c.oid, 'UPDATE')
                       OR has_table_privilege('authenticated', c.oid, 'DELETE')
                ) AS client_grants,
                count(*) FILTER (
                    WHERE c.relkind = 'r'
                      AND (
                          NOT has_table_privilege('service_role', c.oid, 'SELECT')
                          OR NOT has_table_privilege('service_role', c.oid, 'INSERT')
                          OR NOT has_table_privilege('service_role', c.oid, 'UPDATE')
                          OR NOT has_table_privilege('service_role', c.oid, 'DELETE')
                      )
                ) AS missing_backend_grants,
                count(*) FILTER (
                    WHERE c.relkind = 'v'
                      AND NOT has_table_privilege('service_role', c.oid, 'SELECT')
                ) AS missing_view_grants,
                count(*) FILTER (
                    WHERE c.relkind = 'v'
                      AND NOT ('security_invoker=true' = ANY(
                          COALESCE(c.reloptions, ARRAY[]::text[])
                      ))
                ) AS insecure_views
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = ANY(:tables)
              AND c.relkind IN ('r', 'v')
            """
        ),
        {"tables": sorted(_NORMALIZED_REQUIRED_TABLES | _NORMALIZED_REQUIRED_VIEWS)},
    ).mappings().one()

    event_trigger = connection.execute(
        text(
            "SELECT evtenabled FROM pg_event_trigger "
            "WHERE evtname = 'ensure_rls' LIMIT 1"
        )
    ).scalar_one_or_none()
    if event_trigger != "O":
        raise RuntimeError(
            "Normalized database is missing the enabled ensure_rls event trigger."
        )

    if (
        security["rls_disabled"] != 0
        or security["client_grants"] != 0
        or security["insecure_views"] != 0
        or security["missing_backend_grants"] != 0
        or security["missing_view_grants"] != 0
        or security["insecure_sequences"] != 0
    ):
        raise RuntimeError(
            "Normalized database security validation failed: "
            f"RLS-disabled={security['rls_disabled']}, "
            f"client-grants={security['client_grants']}, "
            f"insecure-views={security['insecure_views']}, "
            f"missing-backend-grants={security['missing_backend_grants']}, "
            f"missing-view-grants={security['missing_view_grants']}, "
            f"insecure-sequences={security['insecure_sequences']}."
        )


def validate_normalized_schema_url(database_url: str, federation_slug: str) -> None:
    """Validate normalized schema readiness with a short-lived sync connection."""
    connectable = create_engine(database_url, pool_pre_ping=True)
    try:
        with connectable.connect() as connection:
            validate_normalized_schema(connection, federation_slug)
    finally:
        connectable.dispose()



def set_database_url(config: AlembicConfig, database_url: str) -> None:
    """Store the database URL in the Alembic config.

    Alembic reads its configuration through a ``ConfigParser``, which
    interpolates ``%``. A percent-encoded password in the URL (for
    example ``p%40ss``) would therefore raise a ValueError and the bot
    could not boot. The percent signs are doubled here and unescaped by
    the parser on read, so the URL reaches the driver unchanged.

    The Alembic environment calls this helper too, so the URL survives the
    round trip through the config in both directions.
    """
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def upgrade_head(database_url: str) -> None:
    """Apply every pending migration after checking schema compatibility.

    The URL is passed in rather than read from the environment: the
    application loads its configuration from ``config.env`` as well, so
    the process environment alone is not the single source of truth.
    """
    config = Config(str(_ALEMBIC_INI))
    set_database_url(config, database_url)
    command.upgrade(config, "head")
