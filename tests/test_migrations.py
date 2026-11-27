# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The Alembic wiring must survive every legal database URL."""

from __future__ import annotations

import contextlib
import importlib.util
import pathlib

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts import generate_initial_migration as generator
from tcbot.database import migrations
from tcbot.database.schema import _created_statements, read_schema_file

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


def test_ensure_schema_refuses_a_name_it_cannot_quote() -> None:
    """A schema name that is not an identifier never reaches the SQL.

    The configuration and the Alembic environment already validate the
    name; the helper keeps its own guard so a future caller that passes a
    raw value cannot inject a statement through ``CREATE SCHEMA``.
    """
    with pytest.raises(ValueError, match="plain PostgreSQL identifier"):
        migrations.ensure_schema(
            "postgresql://tcbot@127.0.0.1:1/tcbot", 'bad"; DROP SCHEMA public'
        )


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
    # * The lock connection is out of scope here: this test pins the URL
    # * handed to Alembic, not the advisory-lock plumbing.
    monkeypatch.setattr(
        migrations,
        "_migration_lock",
        lambda _url, _schema: contextlib.nullcontext(),
    )

    migrations.upgrade_head(_PERCENT_URL)

    assert captured == [_PERCENT_URL]


def test_the_schema_travels_to_the_migration_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration fills the schema the application will read.

    The bot passes ``cfg.db_schema`` explicitly, so the value cannot drift
    from the engine when ``DB_SCHEMA`` is absent from the process
    environment (for example when it came from ``config.env``).
    """
    captured: list[str] = []

    def _upgrade(config: Config, revision: str) -> None:
        _ = revision
        captured.append(config.get_main_option("db_schema", ""))

    monkeypatch.setattr(migrations.command, "upgrade", _upgrade)
    lock_schemas: list[str] = []

    def _lock(_url: str, schema: str) -> contextlib.AbstractContextManager[None]:
        lock_schemas.append(schema)
        return contextlib.nullcontext()

    monkeypatch.setattr(migrations, "_migration_lock", _lock)

    migrations.upgrade_head(_PERCENT_URL, "development")

    assert captured == ["development"]
    assert lock_schemas == ["development"]


def test_the_head_revision_reapplies_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-rules-drop head must reinstall the current SQL objects.

    Revision 0023 removed the rules tables but did not reapply the schema
    files, so an upgraded database kept a function that still references a
    dropped table. The forward revision is what repairs those deployments.
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic/versions/0024_reapply_schema_after_rules_removal.py"
    )
    spec = importlib.util.spec_from_file_location("_head_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    called: list[object] = []
    bind = object()
    monkeypatch.setattr(
        module, "apply_schema", lambda connection: called.append(connection)
    )
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)

    module.upgrade()

    assert called == [bind]


def test_every_revision_id_fits_the_version_column() -> None:
    """An overlong revision id aborts the upgrade after its DDL already ran.

    Alembic's ``alembic_version.version_num`` is ``VARCHAR(32)``. A longer id
    makes the version update fail with a truncation error, so the bot cannot
    boot even though the revision's schema changes were valid.
    """
    scripts = ScriptDirectory(
        str(pathlib.Path(__file__).resolve().parents[1] / "alembic")
    )
    for revision in scripts.walk_revisions():
        assert len(revision.revision) <= 32, revision.revision


def test_the_revision_chain_has_a_single_head() -> None:
    """A fork or a missing parent would silently skip part of the schema."""
    scripts = ScriptDirectory(
        str(pathlib.Path(__file__).resolve().parents[1] / "alembic")
    )
    assert len(scripts.get_heads()) == 1


def test_the_outbox_downgrade_removes_its_retention_policy() -> None:
    """A rollback must not leave a policy for a table it just dropped."""
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic/versions/0006_notification_tasks.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "DELETE FROM retention_policies" in source
    assert source.index("DELETE FROM retention_policies") < source.index(
        "moderation_notification_tasks.drop"
    )


def test_the_schema_identifier_guard_accepts_scratch_names() -> None:
    """Dedicated test schemas are plain identifiers like deployment ones."""
    assert migrations.is_safe_schema("tcbot_migration_check_gw0") is True
    assert migrations.is_safe_schema("development") is True
    assert migrations.is_safe_schema('bad"; DROP SCHEMA public') is False
    assert migrations.is_safe_schema("1migration") is False


def test_a_create_trigger_skips_a_table_from_a_later_revision() -> None:
    """An early reapply must not abort on a table it has not created yet."""
    present = (
        "CREATE TRIGGER trg_present BEFORE INSERT ON public.telegram_users "
        "FOR EACH ROW EXECUTE FUNCTION public.f()"
    )
    future = (
        "CREATE TRIGGER trg_future BEFORE INSERT ON public.rule_publications "
        "FOR EACH ROW EXECUTE FUNCTION public.f()"
    )

    assert _created_statements([present, future], {"telegram_users"}) == [present]


def test_the_policy_script_skips_relations_it_cannot_see() -> None:
    """A missing table or view must not abort the current policy files."""
    source = read_schema_file("policies.sql")
    assert source.count("CONTINUE WHEN to_regclass(") == 2


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
