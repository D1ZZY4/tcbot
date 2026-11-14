# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Apply a schema SQL file to a connection.

The schema of the community is deployed from SQL: the functions, the
triggers, the views, the access policies, and the reference data are
one file each, and the loader applies them in order. The file carries
the ``%SCHEMA%`` placeholder, so the same SQL applies to the deployment
schema and to the schema an integration test owns.
"""

from __future__ import annotations

from pathlib import Path

# * The directory of the SQL files, relative to this module.
SQL_DIR: Path = Path(__file__).resolve().parent

# * The placeholder of the schema the objects live in.
SCHEMA_PLACEHOLDER: str = "%SCHEMA%"

# * The files of the schema, in the order they apply. The views read the
# * tables, the functions read the views and the tables, the triggers
# * call the functions, and the policies and the grants come last.
SCHEMA_FILES: tuple[str, ...] = (
    "views.sql",
    "functions.sql",
    "triggers.sql",
    "policies.sql",
    "seed.sql",
)


def read_schema_file(name: str) -> str:
    """Return the SQL of one schema file."""
    return (SQL_DIR / name).read_text(encoding="utf-8")


def file_statements(name: str, schema: str) -> list[str]:
    """Return the statements of one schema file, for the given schema.

    The schema placeholder is replaced before the file is split, so the
    statements name the schema they apply to.
    """
    raw = read_schema_file(name).replace(SCHEMA_PLACEHOLDER, schema)
    return split_statements(raw)


def schema_statements(schema: str) -> list[str]:
    """Return every statement of the schema, in the order they apply."""
    statements: list[str] = []
    for name in SCHEMA_FILES:
        statements.extend(file_statements(name, schema))
    return statements


def split_statements(sql: str) -> list[str]:
    """Return the statements of one SQL text.

    A semicolon only ends a statement when it sits outside every quoted
    region. The function bodies of the schema are dollar quoted, and
    they carry semicolons of their own, so a plain split on the
    semicolon would tear a function apart.
    """
    statements: list[str] = []
    start = 0
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "-" and sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end == -1 else end
            continue
        if char == "/" and sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "'":
            index = _end_of_quoted(sql, index, "'")
            continue
        if char == '"':
            index = _end_of_quoted(sql, index, '"')
            continue
        if char == "$":
            tag_end = sql.find("$", index + 1)
            if tag_end != -1 and _is_dollar_tag(sql[index + 1 : tag_end]):
                tag = sql[index : tag_end + 1]
                end = sql.find(tag, tag_end + 1)
                index = length if end == -1 else end + len(tag)
                continue
        if char == ";":
            statement = sql[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    statement = sql[start:].strip()
    if statement:
        statements.append(statement)
    return statements


def _end_of_quoted(sql: str, start: int, quote: str) -> int:
    """Return the index just after the quoted region that starts at *start*.

    A doubled quote is the escape of a quote inside the region, so the
    region ends at the quote that is not doubled.
    """
    index = start + 1
    length = len(sql)
    while index < length:
        if sql[index] == quote:
            if index + 1 < length and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _is_dollar_tag(text_body: str) -> bool:
    """Return True when *text_body* is a valid dollar quote tag.

    A tag is empty or a name that starts with a letter or an underscore
    and continues with letters, digits, or underscores. Anything else is
    a dollar sign that belongs to the statement, such as a positional
    parameter of a prepared statement.
    """
    if not text_body:
        return True
    if not (text_body[0].isalpha() or text_body[0] == "_"):
        return False
    return all(char.isalnum() or char == "_" for char in text_body)


def execute_statements(conn, statements: list[str]) -> None:
    """Run the statements of the schema on the connection.

    The statements are sent as plain SQL. The driver must not read them
    as a parameterised statement: the schema carries the percent signs
    of ``format()`` and the colons of its idempotency keys, and a
    parameter parser would turn both into placeholders.

    The statements of one file travel in a single round trip. The
    server accepts a script of statements, and the schema holds a few
    hundred of them: sending them one by one would spend minutes on
    the round trips alone when the server is reached over a network.
    """
    if not statements:
        return
    script = ";\n".join(statements) + ";\n"
    cursor = conn.connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()
