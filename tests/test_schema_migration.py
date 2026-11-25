# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The Alembic migrations must produce the schema the application declares.

The integration tests build their tables from the declared metadata, so
they exercise the runtime shape. The bot, on the other hand, applies the
Alembic revisions at startup. Nothing compared the two, so a revision
that drifted from the declared schema would pass the whole suite and
break the boot of a real deployment.

This module migrates an empty schema with the real revision chain and
compares the result against the declared metadata with Alembic's own
comparison, which reports every difference in tables, columns, types,
nullability, indexes, and constraints.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from alembic import command
from tcbot.database.base import metadata
from tests.postgres_support import (
    configured_database_url,
    create_empty_schema,
    drop_schema,
    sync_database_url,
    worker_schema,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# * Every test in this module needs a real PostgreSQL server.
pytestmark = [pytest.mark.postgres]

# * The migration check owns its own schema: it must start empty, and it
# * must not share objects with the metadata-built test schema. The name
# * carries the worker id, because two tests of this module can run on
# * different workers and would otherwise create the same schema at once.
_MIGRATION_SCHEMA: str = worker_schema("tcbot_migration_check")

# * The repository root holds alembic.ini and the alembic/ script directory.
_ROOT: Path = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration_schema() -> Iterator[str]:
    """Yield an empty schema with the Alembic revisions applied to it."""
    url = configured_database_url()
    if url is None:
        pytest.skip(
            "TCBOT_TEST_DATABASE_URL is not set; skipping the schema migration check."
        )
    create_empty_schema(url, _MIGRATION_SCHEMA)

    # * Alembic reads the target schema from its own config before falling
    # * back to DB_SCHEMA or public. PGOPTIONS alone is overridden by that
    # * search path, so the dedicated schema must be set on the config.
    previous_options = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f"-c search_path={_MIGRATION_SCHEMA}"
    try:
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        config.set_main_option("db_schema", _MIGRATION_SCHEMA)
        command.upgrade(config, "head")
    finally:
        if previous_options is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_options

    try:
        yield _MIGRATION_SCHEMA
    finally:
        drop_schema(url, _MIGRATION_SCHEMA)


def test_the_migrations_match_the_declared_schema(
    migration_schema: str,
) -> None:
    """Applying the revisions produces exactly the declared schema."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migration_schema}"},
    )
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True},
            )
            differences = compare_metadata(context, metadata)
    finally:
        engine.dispose()

    assert not differences, (
        "The Alembic migrations drifted from tcbot/database/base.py. "
        "Generate the missing revision with "
        '`uv run alembic revision --autogenerate -m "describe the change"`.'
    )


def test_a_database_stopped_before_the_owner_column_upgrades() -> None:
    """An existing database at revision 0005 must reach head.

    The schema files are current, so revision 0006 applies the current
    registry seed before revision 0007 adds ``job_owner``. A database that
    stopped at 0005 therefore failed the boot on the seed. Revision 0006
    adds the column first; this test drops the column from a migrated
    schema to reproduce that state and then upgrades to head.
    """
    url = configured_database_url()
    if url is None:
        pytest.skip(
            "TCBOT_TEST_DATABASE_URL is not set; skipping the schema migration check."
        )
    schema = worker_schema("tcbot_migration_stepwise")
    create_empty_schema(url, schema)
    previous_options = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f"-c search_path={schema}"
    try:
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        config.set_main_option("db_schema", schema)
        command.upgrade(config, "0005_promotion_request_expiry")
        engine = create_engine(
            sync_database_url(url),
            connect_args={"options": f"-c search_path={schema}"},
        )
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE scheduled_jobs DROP COLUMN job_owner CASCADE"
                )
        finally:
            engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(
            sync_database_url(url),
            connect_args={"options": f"-c search_path={schema}"},
        )
        try:
            with engine.connect() as connection:
                columns = {
                    row[0]
                    for row in connection.exec_driver_sql(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = 'scheduled_jobs'",
                        (schema,),
                    )
                }
                version = connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar()
        finally:
            engine.dispose()
        assert "job_owner" in columns
        # * The test cares that the database reached the head, not which
        # * revision happens to be current, so a new revision needs no edit.
        assert version == ScriptDirectory.from_config(config).get_current_head()
    finally:
        if previous_options is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_options
        drop_schema(url, schema)


def test_the_migration_creates_every_declared_table(
    migration_schema: str,
) -> None:
    """Every table of the declared schema exists after the migration."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migration_schema}"},
    )
    try:
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (migration_schema,),
            )
            present = {row[0] for row in rows}
    finally:
        engine.dispose()

    # * alembic_version is the migration bookkeeping table, not a
    # * declared one.
    present.discard("alembic_version")
    assert present == set(metadata.tables)
