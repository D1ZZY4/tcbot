# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The database objects that SQLAlchemy cannot express.

The tables live in ``tcbot.database.base``. The views, the functions,
the triggers, the access policies, and the reference data live here, as
SQL, so the migration and the test schema apply exactly the same
objects.

The SQL is the deployed contract of the community: it is exported from
the database with ``scripts/dump_schema.py`` and reviewed here. The
``%SCHEMA%`` placeholder stands for the schema the objects live in, so
the same files apply to the deployment and to the schema an integration
test owns.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .loader import (
    SCHEMA_FILES,
    SCHEMA_PLACEHOLDER,
    execute_statements,
    file_statements,
    read_schema_file,
    schema_statements,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# * The name patterns of the objects the schema files create. The drop
# * statements are derived from them, so the objects that are removed
# * are the objects the files create.
_VIEW_PATTERN = re.compile(r"CREATE OR REPLACE VIEW\s+(\S+)", re.IGNORECASE)
_FUNCTION_PATTERN = re.compile(
    r"CREATE OR REPLACE FUNCTION\s+(\S+?)\s*\(", re.IGNORECASE
)
_TRIGGER_PATTERN = re.compile(
    r"CREATE TRIGGER\s+(\S+)\s+.*?\bON\s+(\S+)",
    re.IGNORECASE,
)

__all__ = [
    "SCHEMA_FILES",
    "SCHEMA_PLACEHOLDER",
    "apply_schema",
    "drop_schema",
    "read_schema_file",
    "schema_statements",
    "seed_statements",
]


def _schema_of(connection: Connection) -> str:
    """Return the quoted schema the connection writes to."""
    raw = connection.exec_driver_sql("SELECT current_schema()").scalar()
    schema = str(raw or "public")
    return connection.dialect.identifier_preparer.quote_identifier(schema)


def apply_schema(connection: Connection) -> None:
    """Create the views, functions, triggers, policies, and reference data.

    The statements are idempotent: the views and the functions are
    replaced, the triggers are dropped and recreated, the policies are
    replaced, and the reference data is inserted with an upsert.
    """
    schema = _schema_of(connection)
    for name in SCHEMA_FILES:
        statements = file_statements(name, schema)
        if name == "triggers.sql":
            statements = _drop_statements(name, schema) + statements
        execute_statements(connection, statements)


def drop_schema(connection: Connection) -> None:
    """Remove the views, functions, and triggers of the schema.

    The views come first: they depend on the tables, and a table cannot
    be dropped while a view still reads it.
    """
    schema = _schema_of(connection)
    statements: list[str] = []
    for name in SCHEMA_FILES:
        statements.extend(_drop_statements(name, schema))
    execute_statements(connection, statements)


def seed_statements(schema: str) -> list[str]:
    """Return the reference data statements of the given schema.

    The reference data is idempotent, so a caller can apply it again
    after it removed the rows it owns.
    """
    return file_statements("seed.sql", schema)


def _drop_statements(name: str, schema: str) -> list[str]:
    """Return the statements that remove the objects of one schema file.

    The names come from the file itself, so the objects that are
    dropped are the objects the file creates.
    """
    raw = read_schema_file(name)
    if name == "views.sql":
        views = [match.group(1) for match in _VIEW_PATTERN.finditer(raw)]
        return [
            f"DROP VIEW IF EXISTS {view.replace(SCHEMA_PLACEHOLDER, schema)} CASCADE"
            for view in views
        ]
    if name == "functions.sql":
        functions = [match.group(1) for match in _FUNCTION_PATTERN.finditer(raw)]
        return [
            f"DROP FUNCTION IF EXISTS "
            f"{function.replace(SCHEMA_PLACEHOLDER, schema)} CASCADE"
            for function in functions
        ]
    if name == "triggers.sql":
        triggers: list[str] = []
        for match in _TRIGGER_PATTERN.finditer(raw):
            trigger = match.group(1)
            table = match.group(2).replace(SCHEMA_PLACEHOLDER, schema)
            triggers.append(f"DROP TRIGGER IF EXISTS {trigger} ON {table} CASCADE")
        return triggers
    return []
