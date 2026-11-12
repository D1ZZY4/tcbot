# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The Alembic wiring must survive every legal database URL."""

from __future__ import annotations

import pathlib

import pytest
from alembic.config import Config

from scripts import generate_initial_migration as generator
from tcbot.database import migrations

# * The percent-encoded password is ordinary in a PostgreSQL URL: the
# * password is sent URL-encoded, so a "@" or a "/" in it shows up as
# * "%40" or "%2F".
_PERCENT_URL: str = "postgresql+psycopg://tcbot:p%40ss%2Fword@127.0.0.1:5432/tcbot"

# * The bootstrap generator writes the first revision only.
_GENERATOR = pathlib.Path("scripts/generate_initial_migration.py")


def _config() -> Config:
    """Return a config object without an ini file behind it."""
    return Config()


def test_a_percent_encoded_password_survives_the_config() -> None:
    """The URL reaches the driver unchanged.

    Alembic reads its configuration through a ``ConfigParser``, which
    interpolates ``%``. A raw percent sign would raise a ValueError and
    the bot could not boot, so the helper doubles the percent signs and
    the parser unescapes them on read.
    """
    config = _config()
    migrations.set_database_url(config, _PERCENT_URL)

    assert config.get_main_option("sqlalchemy.url") == _PERCENT_URL


def test_a_plain_password_survives_the_config() -> None:
    """A URL without a percent sign is stored as it is."""
    config = _config()
    url = "postgresql+psycopg://tcbot:plain@127.0.0.1:5432/tcbot"

    migrations.set_database_url(config, url)

    assert config.get_main_option("sqlalchemy.url") == url


def test_the_migration_reaches_the_database_with_a_percent_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The upgrade command receives the decoded URL.

    The migration never connects to the server here: the test only pins
    the value that reaches Alembic.
    """
    captured: list[str] = []

    def _upgrade(config: Config, revision: str) -> None:
        url = config.get_main_option("sqlalchemy.url")
        assert url is not None
        captured.append(url)

    monkeypatch.setattr(migrations.command, "upgrade", _upgrade)

    migrations.upgrade_head(_PERCENT_URL)

    assert captured == [_PERCENT_URL]


def test_the_bootstrap_generator_refuses_to_overwrite_the_first_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The applied revision must never be rewritten.

    The first revision is the database's history. Replacing it would
    leave a deployed database on the old schema while the repository
    claims the change shipped, and Alembic would apply nothing because
    the revision id is already recorded as applied.
    """
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_initial.py").write_text("# existing revision\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        generator.main()

    assert "alembic revision --autogenerate" in str(excinfo.value)
    assert (versions / "0001_initial.py").read_text(encoding="utf-8") == (
        "# existing revision\n"
    )
