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
from tcbot.database.base import metadata
from tcbot.utils.circuit_breaker import postgres as postgres_circuit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.sql import ClauseElement

# * The integration tests read the server URL from the environment and skip
# * when it is unset, so the committed suite never points at a real host.
TEST_DATABASE_URL_ENV: str = "TCBOT_TEST_DATABASE_URL"

# * The integration tests own one PostgreSQL schema inside that database:
# * the objects they create never collide with anything else in it.
TEST_SCHEMA: str = "tcbot_test"
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

    Every xdist worker owns its own schema, so the workers never share
    tables and never delete each other's rows.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if not worker:
        return TEST_SCHEMA
    return f"{TEST_SCHEMA}_{worker}"


def worker_schema(prefix: str) -> str:
    """Return a per-worker schema name derived from *prefix*.

    A module that owns a dedicated schema instead of the shared one
    still has to keep the workers apart: two tests of the same module
    can run on different workers, and they would otherwise create the
    same schema at the same time.
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
    """Create the test schema and every table of the declared schema in it.

    The declared metadata is the source of truth for the table shapes and
    the index opclasses, so the integration tests run against exactly what
    the application asks the database for.
    """
    scope = schema if schema is not None else test_schema()
    create_empty_schema(url, scope)
    scoped = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args=_schema_connect_args(scope),
    )
    try:
        metadata.create_all(scoped)
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
