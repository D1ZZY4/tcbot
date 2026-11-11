"""Generate the initial Alembic migration from the SQLAlchemy metadata.

The migration is generated from the same table definitions the runtime
uses, so the two can never drift. Run it after changing ``base.py``:

    uv run python scripts/generate_initial_migration.py
"""

from __future__ import annotations

import datetime
import pathlib

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from tcbot.database.base import metadata

# * The dialect used to render the DDL. PostgreSQL is the only target.
DIALECT = postgresql.dialect()


def _type_literal(column_type: sa.types.TypeEngine) -> str:
    """Render a column type with the sqlalchemy prefix, nested types included."""
    if isinstance(column_type, sa.ARRAY):
        return f"sa.ARRAY({_type_literal(column_type.item_type)})"
    return f"sa.{column_type!r}"


def _column_literal(column: sa.Column) -> str:
    """Render one column the way Alembic's autogenerate would."""
    parts = [f"sa.Column({column.name!r}, {_type_literal(column.type)}"]
    if column.server_default is not None:
        arg = getattr(column.server_default, "arg", None)
        if isinstance(arg, str):
            parts.append(f"server_default={arg!r}")
        elif isinstance(arg, datetime.datetime):
            parts.append(f"server_default=sa.text({arg.isoformat()!r})")
        elif arg is not None:
            parts.append(f"server_default=sa.text({str(arg)!r})")
    if column.nullable is False:
        parts.append("nullable=False")
    if column.primary_key:
        parts.append("primary_key=True")
    if column.autoincrement not in (None, True, "auto"):
        parts.append(f"autoincrement={column.autoincrement!r}")
    parts.append(")")
    return ", ".join(parts)


def _constraint_literal(constraint: sa.Constraint) -> str | None:
    """Render one table constraint."""
    if isinstance(constraint, sa.PrimaryKeyConstraint):
        cols = ", ".join(repr(c.name) for c in constraint.columns)
        if not cols:
            # * An empty primary key renders to nothing in the DDL, so
            # * emitting the call would only suggest a key that does not
            # * exist.
            return None
        name = constraint.name or ""
        if not name:
            # * An unnamed key takes the database default name
            # * ``<table>_pkey``. The application matches on that name,
            # * so the migration must not pin a different one.
            return f"sa.PrimaryKeyConstraint({cols})"
        return f"sa.PrimaryKeyConstraint({cols}, name={name!r})"
    if isinstance(constraint, sa.UniqueConstraint):
        cols = ", ".join(repr(c.name) for c in constraint.columns)
        name = constraint.name or ""
        return f"sa.UniqueConstraint({cols}, name={name!r})"
    return None


def _index_expression_literal(expression: sa.sql.ClauseElement) -> str:
    """Render one index column, keeping its sort direction.

    A descending column is a SQL expression, not a plain identifier, so it
    is emitted as ``sa.text('<column> DESC')``.
    """
    if isinstance(expression, sa.UnaryExpression):
        modifier = str(getattr(expression.modifier, "__name__", expression.modifier))
        direction = "DESC" if "desc" in modifier.lower() else "ASC"
        inner = expression.element
        column = inner.name if isinstance(inner, sa.Column) else str(inner)
        return f"sa.text('{column} {direction}')"
    if isinstance(expression, sa.Column):
        return repr(expression.name)
    return repr(str(expression))


def _index_literal(index: sa.Index) -> str:
    """Render one index, including its PostgreSQL dialect options."""
    cols = [
        _index_expression_literal(expr)
        for expr in index.expressions
        if isinstance(expr, sa.sql.ClauseElement)
    ]
    index_name = str(index.name) if index.name else ""
    table = index.table
    table_name = str(table.name) if table is not None else ""
    literal = (
        f"op.create_index({index_name!r}, {table_name!r}, "
        f"[{', '.join(cols)}], unique={index.unique!r}"
    )
    options = index.dialect_options.get("postgresql", {})
    where = options.get("where")
    if where is not None:
        literal += (
            f", postgresql_where=sa.text({str(where.compile(dialect=DIALECT))!r})"
        )
    # * The operator class decides whether the index can serve the query.
    # * A prefix match on a text column needs text_pattern_ops under a
    # * non-C collation, and dropping it would leave a sequential scan.
    ops = options.get("ops")
    if ops:
        rendered = ", ".join(f"{key!r}: {value!r}" for key, value in ops.items())
        literal += f", postgresql_ops={{{rendered}}}"
    # * The access method decides how the index is built. A GIN index
    # * serves array containment; a btree index cannot, so dropping the
    # * method turns the lookup into a sequential scan.
    using = options.get("using")
    if using:
        literal += f", postgresql_using={using!r}"
    return literal + ")"


def render() -> str:
    """Return the full migration source."""
    lines: list[str] = [
        "# © Copyright 2024 - 2026 Transsion Core",
        "# © Copyright 2024 - 2026 Dizzy",
        "# © Copyright 2026 Ave Labs",
        "",
        '"""Initial TCF Bot schema.',
        "",
        "Revision ID: 0001_initial",
        "Revises:",
        "Create Date: 2026-11-11",
        "",
        "The tables are generated from ``tcbot.database.base`` so the migration",
        "and the runtime schema cannot drift.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import TYPE_CHECKING",
        "",
        "import sqlalchemy as sa",
        "",
        "from alembic import op",
        "",
        "if TYPE_CHECKING:",
        "    from collections.abc import Sequence",
        "",
        'revision: str = "0001_initial"',
        "down_revision: str | None = None",
        "branch_labels: str | Sequence[str] | None = None",
        "depends_on: str | Sequence[str] | None = None",
        "",
        "",
        "def upgrade() -> None:",
        '    """Create every table and index."""',
    ]
    for table in metadata.sorted_tables:
        lines.append("    op.create_table(")
        lines.append(f"        {table.name!r},")
        lines.extend(f"        {_column_literal(column)}," for column in table.columns)
        for constraint in table.constraints:
            literal = _constraint_literal(constraint)
            if literal:
                lines.append(f"        {literal},")
        lines.append("    )")
        # * The index set has no inherent order, so it is sorted by name
        # * to keep the generated file stable across runs.
        lines.extend(
            f"    {_index_literal(index)}"
            for index in sorted(table.indexes, key=lambda idx: idx.name or "")
        )
    lines.extend(
        [
            "",
            "",
            "def downgrade() -> None:",
            '    """Drop every index and table."""',
        ]
    )
    for table in reversed(metadata.sorted_tables):
        lines.extend(
            f"    op.drop_index({index.name!r}, table_name={table.name!r})"
            for index in sorted(table.indexes, key=lambda idx: idx.name or "")
        )
        lines.append(f"    op.drop_table({table.name!r})")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write the migration file."""
    target = pathlib.Path("alembic/versions/0001_initial.py")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
