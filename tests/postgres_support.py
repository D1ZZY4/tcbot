# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared helpers for the PostgreSQL test modules."""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import os
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tcbot.database import engine as engine_module
from tcbot.database.base import (
    SCHEMA_TABLES,
    connected_chats,
    metadata,
    telegram_chats,
    telegram_users,
)
from tcbot.database.schema import apply_schema, seed_statements
from tcbot.database.schema import drop_schema as drop_schema_objects
from tcbot.utils.circuit_breaker import postgres as postgres_circuit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.sql import ClauseElement

# * The integration tests read the server URL from the environment and skip
# * when it is unset, so the committed suite never points at a real host.
TEST_DATABASE_URL_ENV: str = "TCBOT_TEST_DATABASE_URL"

# * The integration tests own one PostgreSQL schema inside that database:
# * the objects they create never collide with anything else in it.
# *
# * The project uses three schemas and no more: ``public`` for the
# * deployment, ``test`` for the integration tests, and ``development``
# * for a developer working against a shared server. A stray schema
# * would hide a migration that never ran, so nothing else is created.
TEST_SCHEMA: str = "test"
# * The named paramstyle keeps the rendered SQL free of the driver-specific
# * percent escaping, so an assertion can look for the SQL the statement
# * actually expresses.
_DIALECT = postgresql.dialect(paramstyle="named")


def configured_database_url() -> str | None:
    """Return the configured test database URL, or None when it is unset.

    The name avoids the ``test_`` prefix: pytest collects every module
    level callable that starts with it, so the helper would run as an
    empty test in every module that imports it.
    """
    return os.environ.get(TEST_DATABASE_URL_ENV, "").strip() or None


def test_schema() -> str:
    """Return the schema this worker owns.

    The schema does not carry a worker suffix: the project uses one
    schema per purpose, and a second schema would be a schema nobody
    owns. The continuous integration job runs the suite under xdist, and
    two workers cannot share one schema, because they would drop each
    other's tables. One worker therefore owns the schema and the others
    skip the database-backed tests.
    """
    return TEST_SCHEMA


def owns_test_schema() -> bool:
    """Return True when this process may use the test schema.

    Only the first xdist worker owns it. A serial run owns it, because
    there is no other worker to collide with.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    return not worker or worker == "gw0"


def worker_schema(prefix: str) -> str:
    """Return the schema a dedicated worker owns.

    A module that owns a dedicated schema instead of the shared one
    still has to keep the workers apart: two tests of the same module
    can run on different workers, and they would otherwise create the
    same schema at the same time. The name stays inside the project
    vocabulary: it is the shared schema with a worker marker.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if not worker:
        return prefix
    return f"{prefix}_{worker}"


def require_test_database() -> str:
    """Return the test database URL, skipping the test when it is unset."""
    url = configured_database_url()
    if url is None:
        pytest.skip(
            f"{TEST_DATABASE_URL_ENV} is not set; "
            "skipping the PostgreSQL integration test."
        )
    if not owns_test_schema():
        pytest.skip(
            "another xdist worker owns the test schema; "
            "skipping the PostgreSQL integration test."
        )
    return url


def compile_sql(stmt: ClauseElement) -> str:
    """Render one statement as single-line PostgreSQL SQL."""
    return " ".join(str(stmt.compile(dialect=_DIALECT)).split())


def literal_sql(stmt: ClauseElement) -> str:
    """Render one statement as single-line SQL with the values inlined."""
    compiled = stmt.compile(dialect=_DIALECT, compile_kwargs={"literal_binds": True})
    return " ".join(str(compiled).split())


def stmt_params(stmt: ClauseElement) -> dict[str, Any]:
    """Return the bound parameters of one statement."""
    compiled = stmt.compile(dialect=_DIALECT).construct_params() or {}
    params: dict[str, Any] = {}
    for key, value in compiled.items():
        params[str(key)] = value
    return params


def _with_psycopg(url: str) -> str:
    """Return *url* with the plain scheme, whatever driver it started with."""
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def sync_database_url(url: str) -> str:
    """Return *url* with the psycopg 3 driver for the synchronous engine."""
    return "postgresql+psycopg://" + _with_psycopg(url)[len("postgresql://") :]


def async_database_url(url: str) -> str:
    """Return *url* with the async driver, using the production conversion."""
    original = engine_module.cfg
    engine_module.cfg = dataclasses.replace(original, database_url=_with_psycopg(url))
    try:
        return engine_module._database_url()
    finally:
        engine_module.cfg = original


def _schema_connect_args(schema: str | None) -> dict[str, str]:
    """Return the connection arguments that scope the session to *schema*."""
    if not schema:
        return {}
    return {"options": f"-c search_path={schema}"}


def build_test_schema(url: str, schema: str | None = None) -> None:
    """Create the test schema and every object of the declared schema in it.

    The declared metadata is the source of truth for the table shapes and
    the index opclasses, and ``tcbot.database.schema`` is the source of
    truth for the views, the functions, the triggers, the access policies,
    and the reference data. The integration tests therefore run against
    exactly what the application asks the database for.

    The schema is dropped first: a run that failed while it was being
    built leaves the objects of the failed run behind, and the next run
    would apply the schema on top of them.
    """
    scope = schema if schema is not None else test_schema()
    drop_schema(url, scope)
    create_empty_schema(url, scope)
    scoped = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args=_schema_connect_args(scope),
    )
    try:
        metadata.create_all(scoped)
        with scoped.begin() as conn:
            apply_schema(conn)
    finally:
        scoped.dispose()


def create_empty_schema(url: str, schema: str) -> None:
    """Create *schema* without any table in it.

    The migration check needs a schema the Alembic revisions can fill from
    scratch, so it cannot reuse the metadata-built one.
    """
    admin_engine = create_engine(sync_database_url(url), pool_pre_ping=True)
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    finally:
        admin_engine.dispose()


def drop_schema(url: str, schema: str) -> None:
    """Drop *schema* and everything it holds."""
    admin_engine = create_engine(sync_database_url(url), pool_pre_ping=True)
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        admin_engine.dispose()


def drop_test_schema(url: str, schema: str | None = None) -> None:
    """Drop the test schema and everything it holds."""
    scope = schema if schema is not None else test_schema()
    scoped = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args=_schema_connect_args(scope),
    )
    try:
        # * The views read the tables, so they have to go first: a table
        # * cannot be dropped while a view still depends on it.
        with scoped.begin() as conn:
            drop_schema_objects(conn)
        metadata.drop_all(scoped)
    finally:
        scoped.dispose()
    admin_engine = create_engine(sync_database_url(url), pool_pre_ping=True)
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{scope}" CASCADE'))
    finally:
        admin_engine.dispose()


@contextlib.asynccontextmanager
async def use_test_engine(url: str, schema: str | None = None) -> AsyncIterator[None]:
    """Point the shared engine module at *url* for the duration of the block."""
    scope = schema if schema is not None else test_schema()
    async_engine = create_async_engine(
        async_database_url(url),
        pool_pre_ping=True,
        connect_args=_schema_connect_args(scope),
    )
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    previous_engine = engine_module._engine
    previous_factory = engine_module._session_factory
    engine_module._engine = async_engine
    engine_module._session_factory = factory
    try:
        yield
    finally:
        engine_module._engine = previous_engine
        engine_module._session_factory = previous_factory
        await async_engine.dispose()


def reset_postgres_circuit() -> None:
    """Close the shared PostgreSQL circuit so one test cannot affect another."""
    postgres_circuit.reset()


# * The root tables of the community. Truncating them with a cascade
# * empties every table that depends on them, so a test starts from a
# * community without users, groups, or decisions.
TRUNCATE_TABLES: tuple[str, ...] = (
    "telegram_users",
    "telegram_chats",
    "connected_chats",
    "join_requests",
    "role_assignments",
    "promotion_requests",
    "moderation_cases",
    "moderation_actions",
    "audit_events",
)


async def reset_community() -> None:
    """Empty the community tables so the next test starts from zero.

    The append-only guard rejects a delete of the history tables, and it
    rejects a truncation as well. The guards are switched off for the
    reset and switched on again afterwards: a test needs a community
    without history, and the guard has to keep guarding once the test
    is over.

    The cascade reaches the reference tables as well, because the job
    registry names the staff member that changed it. The reference data
    is seeded again afterwards, so a test always finds the role
    catalog, the permission catalog, and the job registry in place.

    The three statements travel in one round trip and one transaction:
    the reset is paid once per test, and the round trips dominated it
    when the server was reached over a network. The transaction is also
    what makes the switch safe: a failing truncation rolls the
    switch-off back, so the guards are never left disabled.
    """
    await engine_module.run_script(_reset_script())
    await reseed_reference_data()


def _reset_script() -> str:
    """Return the script that empties the community tables.

    The guards are switched off, the tables are emptied, and the guards
    are switched on again. The three statements run as one script, so
    the server applies them in a single transaction.
    """
    return (
        f"{_toggle_guards('DISABLE')};\n"
        f"TRUNCATE {', '.join(TRUNCATE_TABLES)} CASCADE;\n"
        f"{_toggle_guards('ENABLE')};\n"
    )


def _toggle_guards(action: str) -> str:
    """Return the script that switches the row triggers of every table.

    The script runs as one statement, because the database does not
    accept a list of tables in a single ``ALTER TABLE`` for this
    action, and a test that waits for one round trip per table spends
    minutes on the network.
    """
    tables = ", ".join(f"'{table}'" for table in SCHEMA_TABLES)
    return (
        "DO $do$\n"
        "DECLARE\n"
        "    table_name text;\n"
        "BEGIN\n"
        f"    FOREACH table_name IN ARRAY ARRAY[{tables}] LOOP\n"
        "        EXECUTE format(\n"
        f"            'ALTER TABLE %I.%I {action} TRIGGER USER',\n"
        "            current_schema(), table_name\n"
        "        );\n"
        "    END LOOP;\n"
        "END;\n"
        "$do$;\n"
    )


async def reseed_reference_data() -> None:
    """Restore the seeded reference data of the community.

    The seed statements are idempotent, so they can run again after a
    reset without changing what they wrote.

    They travel in one round trip on the shared async engine. Sending
    them one by one, and opening a separate synchronous engine for them,
    spent seconds on the round trips alone when the server is reached
    over a network: the reseed is part of every integration test, so
    that cost is paid once per test.
    """
    schema = await engine_module.fetch_value(text("SELECT current_schema()"))
    scope = str(schema or "")
    statements = seed_statements(scope)
    if not statements:
        return
    await engine_module.run_script(";\n".join(statements) + ";\n")


async def seed_users(*user_ids: int) -> None:
    """Insert the Telegram identity rows the community tables reference."""
    unique = list(dict.fromkeys(user_ids))
    if not unique:
        return
    await engine_module.run(
        telegram_users.insert().values([{"user_id": uid} for uid in unique]),
    )


async def seed_chats(*chat_ids: int, connected: bool = True) -> None:
    """Insert the chat identity rows and connect the groups.

    A connected group also gets its configuration row: the trigger that
    prepares the settings of a new group does the same in production.
    """
    unique = list(dict.fromkeys(chat_ids))
    if not unique:
        return
    await engine_module.run(
        telegram_chats.insert().values(
            [
                {"chat_id": cid, "chat_type": "supergroup", "title": f"Group {cid}"}
                for cid in unique
            ]
        ),
    )
    if not connected:
        return
    await engine_module.run(
        connected_chats.insert().values([{"chat_id": cid} for cid in unique]),
    )


async def identity_db_call(op: Callable[[], Awaitable[Any]], **_kwargs: Any) -> Any:
    """Run an engine call inline: no circuit, no pool, no timeout.

    The production helper awaits the thunk it is given, so the double has
    to await it too: a patched engine function that is a coroutine
    function must be driven to completion. A thunk that returns a plain
    value is passed through unchanged.
    """
    result = op()
    if inspect.isawaitable(result):
        return await result
    return result
