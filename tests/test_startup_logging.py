# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Applying the migrations must not reconfigure the application logging.

The bot applies the schema migrations during startup, so the Alembic
environment runs inside the live process. The standard Alembic recipe
calls ``fileConfig()``, which reconfigures the root logger: it removes
every handler the bot installed (including the Telegram error handler)
and resets the root level. The bot would then be silent and would stop
shipping error reports to the operator channel the moment it connects to
the database.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from tcbot.database import migrations
from tcbot.utils.logger import TelegramErrorHandler, set_record_sink
from tests.postgres_support import (
    configured_database_url,
    create_empty_schema,
    drop_schema,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.postgres]

_MIGRATION_SCHEMA: str = "tcbot_logging_check"


@pytest.fixture
def migrated_schema() -> Iterator[str]:
    """Apply the migrations to an empty schema, then drop the schema."""
    url = configured_database_url()
    if url is None:
        pytest.skip(
            "TCBOT_TEST_DATABASE_URL is not set; skipping the startup logging check."
        )
    create_empty_schema(url, _MIGRATION_SCHEMA)

    # * The Alembic environment builds its own engine from the URL, so the
    # * schema scope travels through the libpq connection options.
    previous_options = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f"-c search_path={_MIGRATION_SCHEMA}"
    try:
        migrations.upgrade_head(url)
    finally:
        if previous_options is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_options

    try:
        yield _MIGRATION_SCHEMA
    finally:
        drop_schema(url, _MIGRATION_SCHEMA)


def test_the_migration_keeps_the_root_logging_configuration(
    migrated_schema: str,
) -> None:
    """The root logger keeps its handlers and its level after the migration."""
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level

    # * The migration already ran in the fixture; re-running it is
    # * harmless (the revision is applied) and keeps the assertion on the
    # * exact code path the bot takes at startup.
    url = configured_database_url()
    assert url is not None
    migrations.upgrade_head(url)

    assert list(root.handlers) == handlers_before
    assert root.level == level_before


def test_the_migration_keeps_the_error_handler(migrated_schema: str) -> None:
    """The Telegram error handler survives the migration."""
    root = logging.getLogger()
    assert any(isinstance(handler, TelegramErrorHandler) for handler in root.handlers)


def test_a_record_still_reaches_the_sink_after_the_migration(
    migrated_schema: str,
) -> None:
    """An error raised after the migration still reaches the error sink."""
    shipped: list[str] = []
    previous_sink = None
    set_record_sink(lambda record: shipped.append(record.getMessage()))
    try:
        logging.getLogger("tcbot.probe").error("after the migration")
    finally:
        set_record_sink(previous_sink)

    assert "after the migration" in shipped
