# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Alembic environment for the TCF Bot schema."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic import context

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tcbot.database.base import metadata  # noqa: E402
from tcbot.database.migrations import set_database_url  # noqa: E402

config = context.config


def _configure_migration_logging() -> None:
    """Configure the Alembic logger without touching the application logging.

    ``fileConfig()`` reconfigures the root logger: it removes every handler
    the bot installed (including the Telegram error handler) and resets the
    root level. The bot applies the migrations during startup, so the
    standard call would silence the bot and stop the error reports the
    moment the database connects. The Alembic logger therefore owns its
    own handler and never propagates into the root logger.
    """
    migration_logger = logging.getLogger("alembic")
    migration_logger.handlers.clear()
    migration_logger.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)-5.5s [%(name)s] %(message)s"))
    migration_logger.addHandler(handler)
    migration_logger.setLevel(logging.INFO)


_configure_migration_logging()

# * The bot reads its settings from ``config.env`` when the file is
# * present, so the migration tooling reads it the same way. The
# * migration never needs the bot token: applying a schema change takes
# * the database URL and nothing else.
load_dotenv(find_dotenv("config.env") or find_dotenv(".env"))

# * The URL comes from the caller or from the environment, never from the
# * checked-in ini file, so no credential is ever written to the
# * repository. The migration tooling must stay independent of the bot
# * configuration: applying a schema change needs the database URL and
# * nothing else, so it never asks for the bot token.
url = (
    config.get_main_option("sqlalchemy.url", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)
if not url:
    raise RuntimeError(
        "DATABASE_URL is required to run migrations; set it in config.env or "
        "in the environment."
    )
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://") :]
if url.startswith("postgresql+psycopg://"):
    url = "postgresql://" + url[len("postgresql+psycopg://") :]
# * The URL goes back into the config through the shared helper, so a
# * percent-encoded password survives the ConfigParser interpolation.
set_database_url(config, url)

target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit the migration SQL without connecting to a database."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _connection_options(url: str) -> str:
    """Return the libpq options for the migration connection.

    The timezone pin matches the application engines, so a revision that
    writes a timestamp stores it in the zone the runtime reads it back
    in. The options the connection already carries are kept: the
    migration check runs inside a dedicated schema through ``PGOPTIONS``
    or through an ``options`` parameter in the URL, and the connection
    parameter replaces both of them when it is set.
    """
    parts: list[str] = []
    url_options = make_url(url).query.get("options")
    if url_options:
        # * A repeated query parameter arrives as a tuple; libpq takes the
        # * options as one space-separated string.
        if isinstance(url_options, tuple):
            parts.extend(url_options)
        else:
            parts.append(url_options)
    env_options = os.environ.get("PGOPTIONS", "").strip()
    if env_options:
        parts.append(env_options)
    parts.append("-c timezone=UTC")
    return " ".join(parts)


def run_migrations_online() -> None:
    """Run the migrations against a live database."""
    # * A synchronous engine is enough here: psycopg 3 drives the same
    # * server through its blocking API, and Alembic runs off the event
    # * loop anyway.
    connectable = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": _connection_options(url)},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
