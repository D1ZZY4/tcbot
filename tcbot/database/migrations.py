# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Alembic wiring and schema-compatibility checks for TCF Bot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

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
