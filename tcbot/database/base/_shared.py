# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared definitions for the TCF Bot PostgreSQL schema.

The tables are split across focused modules because the whole schema no
longer fits in one file. Every table belongs to exactly one module, and
the package re-exports them under their table name so the query layer
can import them from one place.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, MetaData, text

# * One metadata object owns every table, so Alembic autogenerate and the
# * runtime schema check read the same definitions.
metadata = MetaData()

# * Timestamps are stored as timezone-aware values. The application works
# * in UTC end to end (see tcbot.utils.time_and_date), so every column
# * carries the same zone.
UTC_NOW = text("now()")
EMPTY_OBJECT = text("'{}'::jsonb")


def one_of(column: str, *values: str) -> str:
    """Return the SQL of a CHECK constraint listing the allowed values."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


def enum_check(name: str, column: str, *values: str) -> CheckConstraint:
    """Return a CHECK constraint restricting *column* to *values*."""
    return CheckConstraint(one_of(column, *values), name=name)
