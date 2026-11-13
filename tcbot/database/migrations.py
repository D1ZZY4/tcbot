# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Alembic wiring: apply the pending schema migrations at startup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from tcbot.database.base import metadata

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.engine import Connection

# * The repository root holds ``alembic.ini`` and the ``alembic/`` script
# * directory. The package lives two levels below it.
_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _ROOT / "alembic.ini"


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


def stamp_bootstrap_schema(
    migration_context: MigrationContext,
    connection: Connection,
    scripts: ScriptDirectory,
) -> None:
    """Stamp a schema that was created outside Alembic.

    A database bootstrapped from the declared metadata instead of by the
    migrations carries every table but no ``alembic_version`` row, so the
    first migration would try to create the tables again and the bot would
    crash-loop on boot with a duplicate-table error.

    The base revision is stamped and the normal upgrade follows, so every
    revision after the one that created the schema still applies. A
    database with a version row, and a database that is empty or only
    partially built, are left to the ordinary upgrade path: a partial
    schema must fail loudly in the migration instead of being stamped.
    """
    if migration_context.get_current_heads():
        return
    declared = set(metadata.tables)
    if not declared:
        return
    existing = set(inspect(connection).get_table_names())
    if not declared.issubset(existing):
        return
    base_revision = scripts.get_base()
    if base_revision is None:
        return
    migration_context.stamp(scripts, base_revision)


def ensure_schema(database_url: str, schema: str) -> None:
    """Create the schema of the application when it does not exist yet.

    The deployment owns ``public``, a developer owns ``development``, and
    the integration tests own ``test``. Those are the only schemas the
    project uses. The schema is created here when it is missing, so a
    fresh database comes up empty and a schema nobody created never
    sends the migration objects into the next schema of the search path.
    """
    if not schema or schema == "public":
        return
    engine = create_engine(scoped_url(database_url, schema), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    finally:
        engine.dispose()


def scoped_url(database_url: str, schema: str) -> str:
    """Return *database_url* with the search path of *schema*.

    The query parameters of the URL are kept: a URL that carries
    ``sslmode`` or any other option still has to carry it when the
    schema is added.
    """
    parsed = make_url(database_url)
    query = dict(parsed.query)
    options = query.get("options")
    search = f"-c search_path={schema}"
    query["options"] = f"{options} {search}" if options else search
    return parsed.set(query=query).render_as_string(hide_password=False)


def upgrade_head(database_url: str) -> None:
    """Apply every pending migration.

    The URL is passed in rather than read from the environment: the
    application loads its configuration from ``config.env`` as well, so
    the process environment alone is not the single source of truth.
    """
    config = Config(str(_ALEMBIC_INI))
    set_database_url(config, database_url)
    command.upgrade(config, "head")
