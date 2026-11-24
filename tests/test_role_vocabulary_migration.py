# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The role vocabulary migration can actually remove stale definitions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from tcbot.database.schema.loader import split_statements

_ROOT = Path(__file__).resolve().parents[1]


def _guard_function() -> str:
    sql = (_ROOT / "tcbot/database/schema/functions/rbac.sql").read_text()
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


def test_the_revision_suspends_the_immutable_fact_guards() -> None:
    """The guarded key rewrites run with their BEFORE triggers disabled.

    The reinstalled guards reject a role-key change, a requested-role change,
    and a system-definition delete. Without suspending them the revision
    fails on exactly the legacy rows it exists to migrate.
    """
    path = _ROOT / "alembic/versions/0013_role_vocabulary.py"
    spec = importlib.util.spec_from_file_location("role_vocab_0013", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    statements: list[str] = []
    fake_op = SimpleNamespace(
        execute=lambda sql: statements.append(str(sql)),
        get_bind=lambda: object(),
    )
    vars(revision)["op"] = fake_op
    vars(revision)["apply_schema"] = lambda bind: None

    revision.upgrade()

    disables = [i for i, sql in enumerate(statements) if "DISABLE TRIGGER" in sql]
    enables = [i for i, sql in enumerate(statements) if "ENABLE TRIGGER" in sql]
    legacy_writes = [
        i
        for i, sql in enumerate(statements)
        if "UPDATE role_assignments SET role_key" in sql
        or "UPDATE promotion_requests SET requested_role_key" in sql
        or "DELETE FROM role_definitions" in sql
    ]
    assert len(disables) == 3
    assert len(enables) == 3
    assert legacy_writes
    assert max(disables) < min(legacy_writes)
    assert min(enables) > max(legacy_writes)
