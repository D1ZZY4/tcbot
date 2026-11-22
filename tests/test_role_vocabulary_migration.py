# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The role vocabulary migration can actually remove stale definitions."""

from __future__ import annotations

from pathlib import Path

from tcbot.database.schema.loader import split_statements

_ROOT = Path(__file__).resolve().parents[1]


def _guard_function() -> str:
    sql = (_ROOT / "tcbot/database/schema/functions.sql").read_text()
    for statement in split_statements(sql):
        if (
            "CREATE OR REPLACE FUNCTION" in statement
            and "guard_system_role_definition" in statement
        ):
            return statement
    raise AssertionError("guard_system_role_definition function not found")


def test_the_delete_branch_returns_the_old_row() -> None:
    statement = _guard_function()
    assert "IF TG_OP = 'DELETE' THEN" in statement
    branch = statement.rsplit("IF TG_OP = 'DELETE' THEN", 1)[1].split("END IF;", 1)[0]
    assert "RETURN OLD;" in branch


def test_the_revision_reapplies_schema_before_deleting_definitions() -> None:
    source = (_ROOT / "alembic/versions/0013_role_vocabulary.py").read_text()
    apply_at = source.index("apply_schema(op.get_bind())")
    delete_at = source.index("DELETE FROM role_definitions")
    assert apply_at < delete_at
