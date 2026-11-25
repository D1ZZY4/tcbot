# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Operator scripts keep their scratch work out of the deployment schema."""

from __future__ import annotations

import pytest

from scripts.check_migration import CHECK_SCHEMA, _alembic_config
from scripts.dump_schema import _require_export, _validate_schema


def test_migration_check_pins_the_alembic_schema() -> None:
    """Alembic must receive the scratch schema, not fall back to public."""
    config = _alembic_config("postgresql://user:pass@localhost/db")
    assert config.get_main_option("db_schema") == CHECK_SCHEMA


@pytest.mark.parametrize("schema", ["public", "test", "development"])
def test_dump_schema_accepts_the_project_schemas(schema: str) -> None:
    """The exporter owns the same three schemas as the application."""
    assert _validate_schema(schema) == schema


@pytest.mark.parametrize("schema", ["", "other", "public;drop"])
def test_dump_schema_rejects_foreign_schemas(schema: str) -> None:
    """A free-form schema name must never rewrite the committed files."""
    with pytest.raises(SystemExit, match="Refusing to export schema"):
        _validate_schema(schema)


def test_dump_schema_refuses_an_empty_export() -> None:
    """An empty dump must not wipe the committed schema files."""
    grouped = {"views.sql": [], "functions.sql": [], "triggers.sql": []}

    with pytest.raises(SystemExit, match="smaller than the committed schema"):
        _require_export(grouped, [])


def test_dump_schema_accepts_a_complete_export() -> None:
    """A dump that carries every object kind passes the safety guard."""
    grouped = {
        "views.sql": ["CREATE VIEW v AS SELECT 1"],
        "functions.sql": ["f"],
        "triggers.sql": ["t"],
    }
    minimums = {
        "views.sql": 1,
        "functions.sql": 1,
        "triggers.sql": 1,
        "seed.sql": 1,
    }

    _require_export(grouped, ["INSERT INTO seed"], minimums)


def test_dump_schema_refuses_a_missing_object_kind() -> None:
    """A partial dump is as unsafe as an empty one."""
    grouped = {
        "views.sql": ["CREATE VIEW v AS SELECT 1"],
        "functions.sql": ["f"],
        "triggers.sql": [],
    }
    minimums = {
        "views.sql": 1,
        "functions.sql": 1,
        "triggers.sql": 1,
        "seed.sql": 1,
    }

    with pytest.raises(SystemExit, match=r"triggers\.sql"):
        _require_export(grouped, ["INSERT INTO seed"], minimums)


def test_dump_schema_refuses_a_partial_but_nonempty_export() -> None:
    """One object per kind must not replace a complete committed schema."""
    grouped = {
        "views.sql": ["CREATE VIEW v AS SELECT 1"],
        "functions.sql": ["f"],
        "triggers.sql": ["t"],
    }
    minimums = {
        "views.sql": 2,
        "functions.sql": 1,
        "triggers.sql": 1,
        "seed.sql": 1,
    }

    with pytest.raises(SystemExit, match="smaller than the committed schema"):
        _require_export(grouped, ["INSERT INTO seed"], minimums)
