# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Alembic wiring: apply the pending schema migrations at startup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config

from alembic import command

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig

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


def upgrade_head(database_url: str) -> None:
    """Apply every pending migration.

    The URL is passed in rather than read from the environment: the
    application loads its configuration from ``config.env`` as well, so
    the process environment alone is not the single source of truth.
    """
    config = Config(str(_ALEMBIC_INI))
    set_database_url(config, database_url)
    command.upgrade(config, "head")
