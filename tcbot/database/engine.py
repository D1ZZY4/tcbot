# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Async SQLAlchemy engine, session boundary, and circuit-breaker guard."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tcbot import cfg
from tcbot.database import migrations
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncConnection
    from sqlalchemy.sql import Executable
log = get_logger(__name__)

# * Caller-side budget for one database operation. The driver has its own
# * socket timeout; this bounds how long a handler waits for the result.
_DB_CALL_TIMEOUT_S: float = 20.0

# * Connection pool. The bot serves dozens of groups, and every handler
# * may read the member cache or the role tables at the same time.
_POOL_SIZE: int = 20
_MAX_OVERFLOW: int = 10
_POOL_TIMEOUT_S: float = 10.0
# * Recycle connections before a proxy or a load balancer drops them.
_POOL_RECYCLE_S: float = 1800.0
_CONNECT_TIMEOUT_S: float = 10.0

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _database_url() -> str:
    """Return the configured PostgreSQL URL with the async driver."""
    url = cfg.database_url.strip()
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def is_connection_error(exc: BaseException) -> bool:
    """Return True when the database link itself failed.

    A dropped connection, a refused socket, or a driver timeout is a
    connection failure. A constraint violation or a syntax error is not:
    the server answered, so the statement was wrong and retrying it
    would fail the same way.
    """
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    if isinstance(exc, DBAPIError):
        orig = getattr(exc, "orig", None)
        if orig is not None and isinstance(orig, (ConnectionError, TimeoutError)):
            return True
        if getattr(exc, "connection_invalidated", False):
            return True
    return False


def is_transient_db_error(exc: BaseException) -> bool:
    """Return True when the failure is worth retrying or counting.

    A dropped connection or a timeout is transient; a constraint
    violation or a syntax error is an application bug and must not open
    the circuit.
    """
    if is_connection_error(exc):
        return True
    # * A raw connection error raised inside a database operation is a
    # * link failure even when the driver did not wrap it.
    if isinstance(exc, ConnectionError):
        return True
    # * Callers wrap database calls in asyncio.timeout for slow-path
    # * bounds; a timeout there is a hang, not an application error.
    return isinstance(exc, TimeoutError)


def is_database_error(exc: BaseException) -> bool:
    """Return True when the exception was raised by the database layer."""
    return isinstance(exc, SQLAlchemyError)


def _counts_toward_circuit(exc: Exception) -> bool:
    """Circuit predicate: only transient database errors count as failures."""
    return is_transient_db_error(exc)


def constraint_name(exc: BaseException) -> str:
    """Return the name of the constraint an integrity error violated.

    PostgreSQL reports the violated constraint in the error diagnostic, so
    a caller can tell a duplicate identifier apart from a duplicate
    partial index without matching on the message text.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return str(getattr(diag, "constraint_name", "") or "")


def engine() -> AsyncEngine:
    """Return the shared engine, raising when the database is not connected."""
    if _engine is None:
        raise RuntimeError("Database not initialised; call connect() first.")
    return _engine


def is_connected() -> bool:
    """Return True once a connection has been established via connect()."""
    return _engine is not None


@contextlib.asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on success and rolls back on failure.

    One session per operation: PostgreSQL transactions are short, and a
    long-lived session would hold a pooled connection across awaits.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialised; call connect() first.")
    async with _session_factory() as sess:
        try:
            yield sess
            await sess.commit()
        except BaseException:
            await sess.rollback()
            raise


@contextlib.asynccontextmanager
async def read_connection() -> AsyncIterator[AsyncConnection]:
    """Yield a connection for a read-only statement.

    A read needs no transaction, so the connection runs in autocommit and
    the statement costs one round trip instead of one plus the COMMIT that
    closes the transaction. Measured against the deployment schema, a
    single-row lookup drops from 0.77 ms to 0.47 ms.

    The isolation level is reverted when the connection returns to the
    pool, so a write that follows still runs in a normal transaction.
    """
    if _engine is None:
        raise RuntimeError("Database not initialised; call connect() first.")
    connection = await _engine.connect()
    try:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        yield connection
    finally:
        await connection.close()


async def fetch_all(stmt: Executable) -> list[dict[str, Any]]:
    """Return every row of one SELECT as plain dicts."""
    async with read_connection() as conn:
        result = await conn.execute(stmt)
        return [dict(row) for row in result.mappings()]


async def fetch_one(stmt: Executable) -> dict[str, Any] | None:
    """Return the first row of one SELECT as a plain dict, or None."""
    async with read_connection() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row is not None else None


async def fetch_value(stmt: Executable) -> Any | None:
    """Return the first column of the first row of one SELECT."""
    async with read_connection() as conn:
        result = await conn.execute(stmt)
        return result.scalar()


async def fetch_count(stmt: Executable) -> int:
    """Return the integer result of one counting SELECT.

    The statement must project a single aggregate count, as in
    ``select(func.count()).select_from(table)``. Use :func:`count_rows`
    to count the rows of an arbitrary selection.
    """
    value = await fetch_value(stmt)
    return int(value or 0)


async def count_rows(stmt: Executable) -> int:
    """Return the number of rows one SELECT returns.

    The statement is wrapped in a counting query, so the result is the
    row count and never the first column of the first row.
    """
    return await fetch_value(
        select(func.count()).select_from(stmt.subquery())  # type: ignore[attr-defined]
    )


async def run(stmt: Executable) -> int:
    """Run one write and return the number of affected rows."""
    async with session() as sess:
        result = await sess.execute(stmt)
        # * A write returns a cursor result, which carries the affected
        # * row count. The generic result type does not expose it.
        return cast("CursorResult", result).rowcount


async def run_returning(stmt: Executable) -> list[dict[str, Any]]:
    """Run one write with a RETURNING clause and return the stored rows."""
    async with session() as sess:
        result = await sess.execute(stmt)
        return [dict(row) for row in result.mappings()]


async def db_call[T](
    op: Callable[[], Awaitable[T]],
    *,
    timeout: float | None = _DB_CALL_TIMEOUT_S,
) -> T:
    """Run one database operation through the circuit breaker and a timeout.

    Every database read and write goes through this boundary so a dead
    database fails fast for every caller instead of each helper inventing
    its own timeout. The circuit opens after repeated transient failures
    and rejects further calls without touching the server.
    """

    async def _run() -> T:
        if timeout is None:
            return await op()
        async with asyncio.timeout(timeout):
            return await op()

    return await _cb.postgres.call(_run(), count_failure=_counts_toward_circuit)


async def run_transaction[T](
    op: Callable[[AsyncSession], Awaitable[T]],
    *,
    timeout: float | None = _DB_CALL_TIMEOUT_S,
) -> T:
    """Run one unit of work that spans several statements atomically.

    Every statement the callback issues on the session runs in the same
    transaction, so the unit either lands completely or not at all. Use
    it when two writes must agree, such as a warning history row and the
    counter that decides the auto-ban threshold. A compensating delete
    after the fact cannot restore that guarantee: a crash between the
    two writes would leave the pair inconsistent.
    """

    async def _run() -> T:
        async with session() as sess:
            return await op(sess)

    return await db_call(_run, timeout=timeout)


async def connect() -> None:
    """Apply the schema migrations, create the engine, and verify the link."""
    global _engine, _session_factory
    url = _database_url()
    # * The migrations run before the engine is published, so the schema is
    # * current before the first handler query reaches the database. A
    # * fresh deployment therefore boots against an empty database.
    await asyncio.to_thread(migrations.upgrade_head, url)
    _engine = create_async_engine(
        url,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_timeout=_POOL_TIMEOUT_S,
        pool_recycle=_POOL_RECYCLE_S,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _CONNECT_TIMEOUT_S,
            # * The application works in UTC end to end; the session zone
            # * decides how a timestamp without one is read back.
            "options": "-c timezone=UTC",
        },
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    try:
        await _cb.postgres.call(
            _ping(),
            count_failure=_counts_toward_circuit,
        )
    except BaseException:
        # * The engine is not published yet, so close() can never reclaim
        # * it. Leaking it would keep a pool and its sockets alive per
        # * failed attempt, which accumulates on the serverless path.
        await _dispose()
        raise
    log.info("PostgreSQL connected")


async def _ping() -> None:
    """Verify the connection with a trivial statement."""
    async with session() as sess:
        await sess.execute(text("SELECT 1"))


async def _dispose() -> None:
    """Dispose the engine and drop the session factory."""
    global _engine, _session_factory
    engine_obj, _engine = _engine, None
    _session_factory = None
    if engine_obj is not None:
        await engine_obj.dispose()


async def close() -> None:
    """Close the shared engine, releasing pooled connections (shutdown path).

    Called after every drain in ``_post_shutdown`` so no in-flight write
    outlives the pool. Safe to call without a prior connect.
    """
    await _dispose()
