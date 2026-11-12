# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""PostgreSQL-backed Kurigram storage engine for the shared MTProto session."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import msgspec
from pyrogram.storage import Storage, UpdateState
from pyrogram.storage.sqlite_storage import SQLiteStorage, get_input_peer
from sqlalchemy import ARRAY, Text, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.sql import Executable

from tcbot.database.base import mtproto_state
from tcbot.database.engine import db_call, fetch_all, fetch_one, run, run_returning
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator
    from typing import Any

log = get_logger(__name__)

# ────────────────────────── Write retry ────────────────────────── #

# * Maximum retries for transient write failures (e.g. a failover or a
# * serialization conflict). Each retry waits exponentially: 0.5s, 1s, 2s.
_MAX_WRITE_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 0.5

# * SQLSTATE 40001 (serialization failure) and 40P01 (deadlock detected)
# * are the PostgreSQL equivalents of a retryable write concern error:
# * the transaction never ran, so the same statement succeeds on the next
# * attempt.
_TRANSIENT_SQLSTATES: frozenset[str] = frozenset({"40001", "40P01"})

# * A connection-level refusal is reported as SQLSTATE class 08 (the
# * server is unreachable, the socket died, the host said no) or as
# * 57P03 "cannot connect now": the server is up but refuses connections.
_CONNECTIVITY_SQLSTATES: frozenset[str] = frozenset({"57P03"})


def _sqlstate(exc: BaseException) -> str:
    """Return the SQLSTATE of a driver error, or an empty string."""
    orig = getattr(exc, "orig", None)
    return str(getattr(orig, "sqlstate", "") or "")


def _is_connectivity_failure(exc: BaseException) -> bool:
    """Return True when the server could not be reached at all.

    A refused or dropped connection has already burned the driver's own
    connect timeout, so retrying only multiplies the outage wait.
    """
    if not isinstance(exc, OperationalError):
        return False
    state = _sqlstate(exc)
    return state.startswith("08") or state in _CONNECTIVITY_SQLSTATES


def _is_transient_write_error(exc: BaseException) -> bool:
    """Return True when *exc* is a retryable PostgreSQL write failure.

    The PostgreSQL equivalents of a retryable MongoDB write concern
    error are a serialization failure (SQLSTATE 40001), a deadlock
    (40P01) and a dropped connection (InterfaceError): the statement
    never took effect, so the next attempt can simply run it again.
    """
    if isinstance(exc, InterfaceError):
        # * The pool dropped the connection mid-statement; the next
        # * attempt is served by a fresh socket.
        return True
    if isinstance(exc, OperationalError):
        return _sqlstate(exc) in _TRANSIENT_SQLSTATES
    return False


async def _retry_write(
    op: Callable[[], Awaitable[Any]], *, timeout: float | None = None
) -> Any:
    """Execute *op* with retries on transient PostgreSQL write failures.

    Pyrogram's ``handle_updates()`` background task persists update states
    through this store.  A failover or a serialization conflict raises an
    ``OperationalError`` (SQLSTATE 40001) or drops the connection with an
    ``InterfaceError``.  Because the task is fire-and-forget, the
    exception is never retrieved and the event loop reports it as an
    unhandled task exception.

    Retrying transparently keeps the session alive through a brief
    failover without flooding the error channel.

    Connectivity failures already burned a full connect timeout, so they
    are not retried: they degrade immediately. The open PostgreSQL circuit
    also degrades immediately. Only the lease-claim path needs a unique
    violation to propagate for fencing; it calls the database directly
    instead of using this helper.

    *op* must be cheap to rebuild so retries re-execute the operation
    instead of reusing its result: callers pass a zero-argument thunk
    that performs the async write when awaited.

    *timeout* replaces the engine budget for an operation that owns more
    than one statement. A batched write runs its chunks one after the
    other inside a single call, so the budget of a single statement would
    cut a long batch short. None keeps the engine default.
    """

    async def _attempt() -> Any:
        if timeout is None:
            return await db_call(op)
        return await db_call(op, timeout=timeout)

    last_exc: BaseException | None = None
    for attempt in range(_MAX_WRITE_RETRIES):
        try:
            return await _attempt()
        except asyncio.CancelledError:
            raise
        except IntegrityError:
            # * A unique violation is fencing control flow, never a
            # * transient failure: it must reach the caller.
            raise
        except CircuitOpenError as exc:
            log.warning("MTProto write failed (circuit open): %s", exc, exc_info=True)
            return None
        except (OperationalError, InterfaceError) as exc:
            if _is_connectivity_failure(exc):
                # * The server could not be reached: the connect timeout
                # * already elapsed, so retrying only delays the degrade.
                log.warning(
                    "MTProto write failed (connectivity): %s", exc, exc_info=True
                )
                return None
            if not _is_transient_write_error(exc) or attempt == _MAX_WRITE_RETRIES - 1:
                # * Non-transient (or exhausted) failure: log and degrade
                # * instead of propagating to Pyrogram's handle_updates task,
                # * which would crash update handling for the whole session.
                log.warning(
                    "MTProto write failed (non-transient): %s", exc, exc_info=True
                )
                return None
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2**attempt)
            log.debug(
                "MTProto write attempt %d/%d failed (transient): %s; retrying in %.1fs",
                attempt + 1,
                _MAX_WRITE_RETRIES,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    # * pragma: no cover - the loop always returns or raises before reaching here.
    raise last_exc  # type: ignore[misc]


# ────────────────────────────── Keys ───────────────────────────── #
# * The table holds one row per key, scoped by the session namespace:
# * ``<ns>:kv:<name>`` scalars, ``<ns>:peer:<peer_id>`` peers,
# * ``<ns>:ustate:<id>`` update states and ``<ns>:lock:mtproto_owner``
# * the single-owner lease.


def _like_escape(value: str) -> str:
    """Escape *value* so it matches literally inside a SQL LIKE pattern."""
    # * The escape character of the default LIKE operator is the
    # * backslash, so the wildcards it protects must be escaped with it.
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ──────────────────────── Single-owner lease ───────────────────── #


async def claim_owner(store: PostgresStorage, owner: str, *, ttl_s: float) -> bool:
    """Atomically claim the single-owner lease for *owner*.

    Succeeds on a free lease, an expired lease (previous holder died
    without releasing), or a first-time insert won against a
    concurrent claimant (the loser gets no inserted row). A live
    lease held by anyone else refuses. Only CancelledError
    propagates; every other failure returns False so callers degrade
    instead of sharing one auth key twice.
    """
    now = time.time()
    lease_id = store._lease_id()

    async def _take() -> Any:
        return await db_call(
            lambda: run_returning(
                mtproto_state.update()
                .where(
                    mtproto_state.c.id == lease_id,
                    # * One statement decides the takeover: the row lock
                    # * plus the re-check of the predicate after a
                    # * concurrent commit makes the update atomic, so
                    # * two claimants can never both take the lease.
                    or_(
                        mtproto_state.c.owner == owner,
                        mtproto_state.c.expires_at < now,
                    ),
                )
                .values(owner=owner, expires_at=now + ttl_s)
                .returning(mtproto_state.c.id)
            )
        )

    # * The claim path calls the database directly instead of _retry_write:
    # * _retry_write returns None on degrade, which is indistinguishable
    # * from a legitimate no-row None here and would fall through to the
    # * insert step and report a lease that was never held. Letting
    # * connectivity and circuit errors propagate keeps outage claims at
    # * False, where fencing is safe.
    try:
        if await _take():
            return True
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("MTProto lease claim failed")
        return False

    # * No row (first boot) or a live foreign lease: exactly one
    # * concurrent insert wins; the loser degrades instead of sharing
    # * the auth key.
    async def _first() -> list[dict[str, Any]]:
        return await db_call(
            lambda: run_returning(
                pg_insert(mtproto_state)
                .values(id=lease_id, owner=owner, expires_at=now + ttl_s)
                # * The primary key makes the loser of the race skip the
                # * insert instead of raising, so no lease is ever held
                # * by two owners. The RETURNING clause reports the
                # * winner: an insert that skipped the row returns
                # * nothing.
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(mtproto_state.c.id)
            )
        )

    try:
        return bool(await _first())
    except asyncio.CancelledError:
        raise
    except IntegrityError:
        return False
    except Exception:
        log.exception("MTProto lease first-claim insert failed")
        return False


async def refresh_owner(store: PostgresStorage, owner: str, *, ttl_s: float) -> bool:
    """Renew the lease; False when someone else owns it (fencing)."""
    lease_id = store._lease_id()
    expires_at = time.time() + ttl_s
    affected = await db_call(
        lambda: run(
            mtproto_state.update()
            .where(mtproto_state.c.id == lease_id, mtproto_state.c.owner == owner)
            .values(expires_at=expires_at)
        )
    )
    return affected > 0


async def release_owner(store: PostgresStorage, owner: str) -> None:
    """Best-effort lease release; expiry covers leftovers after a crash."""
    lease_id = store._lease_id()
    try:
        await db_call(
            lambda: run(
                mtproto_state.delete().where(
                    mtproto_state.c.id == lease_id, mtproto_state.c.owner == owner
                )
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto lease release failed (expiry covers it): %s", exc)


# ──────────────────────────── Batched writes ────────────────────── #
# * Kurigram hands the store the whole peer list of a session in one
# * call, and the same for the update states. Writing that list row by
# * row cost one transaction per row, so a busy session paid thousands
# * of round trips for a single save. The helpers below turn a list
# * into one statement per bounded chunk instead.

# * A chunk bounds the rows one statement carries, so a session with a
# * huge peer list cannot build an unbounded multi-row INSERT. The size
# * stays well under the PostgreSQL bind-parameter ceiling and keeps the
# * number of chunks of a realistic session in the low single digits.
_MAX_BATCH_ROWS: int = 500

# * A batched write owns one budget for all of its chunks, and the
# * chunks run one after the other inside the same call. The engine
# * budget of a single statement would cut a long batch short, so the
# * batch gets a budget that covers the whole list.
_BATCH_TIMEOUT_S: float = 60.0

# * The update state fields a merge can carry. Every state writes the
# * same set, so one statement covers a whole list of them.
_STATE_FIELDS: tuple[str, ...] = ("pts", "qts", "date", "seq")


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Split *rows* into consecutive chunks of at most *size* rows."""
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last row per row ID.

    One statement cannot touch the same row twice, so a repeated ID
    would abort the whole statement with a cardinality violation. The
    per-row writes applied the rows in order, so the last row of an ID
    is the one that survived.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row["id"]] = row
    return list(latest.values())


async def _run_statement(stmt: Executable) -> None:
    """Execute one write statement.

    The statement runs inside the caller's transaction boundary, so it
    must not open a second one: a nested boundary would record one
    failure twice against the shared circuit breaker.
    """
    await run(stmt)


async def _write_rows(
    rows: list[dict[str, Any]],
    build: Callable[[list[dict[str, Any]]], Executable],
) -> None:
    """Write *rows* through *build*, one statement per bounded chunk.

    The chunks run one after the other inside a single guarded call, so
    the whole batch shares one breaker slot and one budget.
    """
    for chunk in _chunks(rows, _MAX_BATCH_ROWS):
        await _run_statement(build(chunk))


def _update_state_rows(
    store: PostgresStorage, states: Iterable[UpdateState]
) -> list[dict[str, Any]]:
    """Build the update-state rows, one per state ID.

    A repeated state ID keeps the last known value of every field, which
    is what the per-row writes produced: each of them touched only the
    fields it knew, so the last write of a field won and the fields it
    did not know survived. A state that knows no field at all is
    dropped, because the per-row writes never created a row for it.
    """
    merged: dict[str, dict[str, Any]] = {}
    blank: dict[str, Any] = dict.fromkeys(_STATE_FIELDS)
    for state in states:
        state_id = store._ustate(state.id)
        row = merged.get(state_id)
        if row is None:
            row = {"id": state_id, **blank}
            merged[state_id] = row
        for field in _STATE_FIELDS:
            value = getattr(state, field)
            if value is not None:
                row[field] = value
    return [
        row
        for row in merged.values()
        if any(row[field] is not None for field in _STATE_FIELDS)
    ]


def _update_state_upsert(rows: list[dict[str, Any]]) -> Executable:
    """Build the update-state upsert statement for *rows*."""
    stmt = pg_insert(mtproto_state).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=["id"],
        # * A field the new state does not know keeps its stored value:
        # * the same COALESCE merge the SQLite storage performs, and the
        # * same result the per-row writes produced.
        set_={
            field: func.coalesce(stmt.excluded[field], mtproto_state.c[field])
            for field in _STATE_FIELDS
        },
    )


# ────────────────────────────── Peers ──────────────────────────── #


def _peer_rows(
    store: PostgresStorage,
    peers: Iterable[tuple[int, int, str, str | None]],
    now: int,
) -> list[dict[str, Any]]:
    """Build the peer rows, one per peer."""
    rows = [
        {
            "id": store._peer(peer_id),
            "access_hash": access_hash,
            "type": peer_type,
            "phone_number": phone_number,
            "updated_on": now,
            # * A new peer row starts with an empty name list; the
            # * conflict clause leaves a stored list untouched.
            "usernames": [],
        }
        for peer_id, access_hash, peer_type, phone_number in peers
    ]
    return _dedupe_by_id(rows)


def _peer_upsert(rows: list[dict[str, Any]]) -> Executable:
    """Build the peer upsert statement for *rows*."""
    stmt = pg_insert(mtproto_state).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            # * The excluded row carries the values of the peer that
            # * caused the conflict, so every row of the batch updates
            # * its own row exactly as a per-row write did.
            "access_hash": stmt.excluded.access_hash,
            "type": stmt.excluded.type,
            "phone_number": stmt.excluded.phone_number,
            "updated_on": stmt.excluded.updated_on,
        },
    )


async def update_peers(
    store: PostgresStorage, peers: Iterable[tuple[int, int, str, str | None]]
) -> None:
    """Upsert peers, preserving stored usernames like the usernames table does."""
    now = int(time.time())
    rows = _peer_rows(store, peers, now)
    if not rows:
        return
    await _retry_write(
        lambda: _write_rows(rows, _peer_upsert), timeout=_BATCH_TIMEOUT_S
    )


def _username_rows(
    store: PostgresStorage,
    usernames: Iterable[tuple[int, list[str | None]]],
    now: int,
) -> list[dict[str, Any]]:
    """Build the name-list rows, one per peer."""
    rows = [
        {
            "id": store._peer(peer_id),
            "usernames": [name for name in names if name is not None],
            "updated_on": now,
        }
        for peer_id, names in usernames
    ]
    return _dedupe_by_id(rows)


def _username_upsert(rows: list[dict[str, Any]]) -> Executable:
    """Build the name-list upsert statement for *rows*."""
    stmt = pg_insert(mtproto_state).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=["id"],
        # * Only the names and the timestamp change: the stored access
        # * hash and peer type survive a names-only write.
        set_={
            "usernames": stmt.excluded.usernames,
            "updated_on": stmt.excluded.updated_on,
        },
    )


async def update_usernames(
    store: PostgresStorage, usernames: Iterable[tuple[int, list[str | None]]]
) -> None:
    """Replace the username list of each given peer.

    Bumps ``updated_on`` alongside the names: username freshness is
    evaluated against that timestamp, so a names-only write must not
    leave the previous write time behind.
    """
    now = int(time.time())
    rows = _username_rows(store, usernames, now)
    if not rows:
        return
    await _retry_write(
        lambda: _write_rows(rows, _username_upsert), timeout=_BATCH_TIMEOUT_S
    )


def _peer_input(doc: dict[str, Any], peer_id: int, message: str) -> Any:
    """Build the InputPeer from a peer row, or raise KeyError when it is unusable.

    A peer row without an access hash or a type cannot address a
    Telegram peer, so it is reported as a miss instead of handing a
    half-built peer to the API.
    """
    access_hash = doc.get("access_hash")
    peer_type = doc.get("type")
    if access_hash is None or peer_type is None:
        raise KeyError(message)
    return get_input_peer(peer_id, access_hash, peer_type)


async def get_peer_by_id(store: PostgresStorage, peer_id: int) -> Any:
    """Return the InputPeer for *peer_id*, or raise KeyError like SQLiteStorage."""
    doc = await db_call(
        lambda: fetch_one(
            select(
                mtproto_state.c.access_hash,
                mtproto_state.c.type,
            ).where(mtproto_state.c.id == store._peer(peer_id))
        )
    )
    if doc is None:
        raise KeyError(f"ID not found: {peer_id}")
    return _peer_input(doc, peer_id, f"ID not found: {peer_id}")


async def get_peer_by_username(store: PostgresStorage, username: str) -> Any:
    """Return the freshest InputPeer for *username*, or raise KeyError."""
    doc = await db_call(
        lambda: fetch_one(
            select(
                mtproto_state.c.id,
                mtproto_state.c.access_hash,
                mtproto_state.c.type,
                mtproto_state.c.updated_on,
            )
            .where(
                mtproto_state.c.id.like(f"{store._ns_like}:peer:%"),
                # * The containment operator is the one the GIN index
                # * over the name array can serve; "= ANY(...)" is not.
                mtproto_state.c.usernames.op("@>")(literal([username], ARRAY(Text))),
            )
            .order_by(mtproto_state.c.updated_on.desc())
            .limit(1)
        )
    )
    if doc is None:
        raise KeyError(f"Username not found: {username}")
    updated_on = doc.get("updated_on") or 0
    if abs(time.time() - updated_on) > SQLiteStorage.USERNAME_TTL:
        raise KeyError(f"Username expired: {username}")
    peer_id = int(str(doc["id"]).rsplit(":", 1)[1])
    return _peer_input(doc, peer_id, f"Username not found: {username}")


async def get_peer_by_phone_number(store: PostgresStorage, phone_number: str) -> Any:
    """Return the InputPeer for *phone_number*, or raise KeyError."""
    doc = await db_call(
        lambda: fetch_one(
            select(
                mtproto_state.c.id,
                mtproto_state.c.access_hash,
                mtproto_state.c.type,
            ).where(
                mtproto_state.c.id.like(f"{store._ns_like}:peer:%"),
                mtproto_state.c.phone_number == phone_number,
            )
        )
    )
    if doc is None:
        raise KeyError(f"Phone number not found: {phone_number}")
    peer_id = int(str(doc["id"]).rsplit(":", 1)[1])
    return _peer_input(doc, peer_id, f"Phone number not found: {phone_number}")


# ───────────────────────────── Storage ─────────────────────────── #


class PostgresStorage(Storage):
    """Kurigram :class:`Storage` persisted in the ``mtproto_state`` table.

    Semantics mirror Kurigram's ``SQLiteStorage`` exactly (same KeyError
    misses, same 8h username TTL, same COALESCE-style update-state merge);
    only the backend differs.
    """

    def __init__(self, namespace: str) -> None:
        """Scope every key under *namespace* so sessions never collide."""
        self._ns = namespace
        # * Pre-escaped once: the namespace feeds several LIKE filters
        # * below, and an unescaped metacharacter there would widen
        # * every peer/username/state scan past this session's keys.
        self._ns_like = _like_escape(namespace)

    # ── key helpers ── #
    # * Table ``mtproto_state``, one row per key, scoped by
    # * namespace: ``<ns>:kv:<name>`` scalars, ``<ns>:peer:<peer_id>``
    # * peers, ``<ns>:ustate:<id>`` update states.

    def _kv(self, name: str) -> str:
        """Build the row ID for scalar *name*."""
        return f"{self._ns}:kv:{name}"

    def _peer(self, peer_id: int) -> str:
        """Build the row ID for *peer_id*."""
        return f"{self._ns}:peer:{peer_id}"

    def _ustate(self, state_id: int) -> str:
        """Build the row ID for update state *state_id*."""
        return f"{self._ns}:ustate:{state_id}"

    # ── lifecycle ── #

    async def open(self) -> None:
        """No-op: the schema is owned by the shared engine, rows are created on first write."""
        return

    async def save(self) -> None:
        """Bump the stored date, mirroring SQLiteStorage.save()."""
        await self.date(int(time.time()))

    async def close(self) -> None:
        """No-op: the connection pool is owned by the shared engine."""
        return

    async def delete(self) -> None:
        """Drop every row in this namespace with transient-error retry."""
        await _retry_write(
            lambda: run(
                mtproto_state.delete().where(
                    mtproto_state.c.id.like(f"{self._ns_like}:%")
                )
            )
        )

    # ── scalar accessors (same object-sentinel contract as SQLiteStorage) ── #

    async def _get_scalar(self, name: str) -> Any:
        """Read scalar *name*, or None when never written."""
        row = await db_call(
            lambda: fetch_one(
                select(mtproto_state.c.value).where(
                    mtproto_state.c.id == self._kv(name)
                )
            )
        )
        if row is None:
            return None
        raw = row.get("value")
        if raw is None:
            return None
        # * The session holds opaque Python objects (the authorization
        # * key is raw bytes), so the payload travels as msgpack.
        return msgspec.msgpack.decode(bytes(raw))

    async def _set_scalar(self, name: str, value: Any) -> None:
        """Upsert scalar *name* with transient-error retry."""
        kv = self._kv(name)
        payload = msgspec.msgpack.encode(value)

        await _retry_write(
            lambda: run(
                pg_insert(mtproto_state)
                .values(id=kv, value=payload)
                .on_conflict_do_update(index_elements=["id"], set_={"value": payload})
            )
        )

    def _accessor(self, name: str, value: Any = object) -> Awaitable[Any]:
        """Build a dual getter/setter coroutine for scalar *name*."""

        async def _run() -> Any:
            if value is object:
                return await self._get_scalar(name)
            await self._set_scalar(name, value)
            return None

        return _run()

    async def dc_id(self, value: int | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the data-center ID."""
        return await self._accessor("dc_id", value)

    async def api_id(self, value: int | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the API ID."""
        return await self._accessor("api_id", value)

    async def server_address(self, value: str | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the server address."""
        return await self._accessor("server_address", value)

    async def port(self, value: int | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the server port."""
        return await self._accessor("port", value)

    async def test_mode(  # type: ignore[override]
        self,
        value: bool | type[object] = object,  # noqa: FBT001
    ) -> Any:
        """Get or set test-mode flag."""
        return await self._accessor("test_mode", value)

    async def auth_key(self, value: bytes | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the authorization key."""
        return await self._accessor("auth_key", value)

    async def date(self, value: int | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the stored date."""
        return await self._accessor("date", value)

    async def user_id(self, value: int | type[object] = object) -> Any:  # type: ignore[override]
        """Get or set the authorized user ID (None = fresh session)."""
        return await self._accessor("user_id", value)

    async def is_bot(  # type: ignore[override]
        self,
        value: bool | type[object] = object,  # noqa: FBT001
    ) -> Any:
        """Get or set the bot-session flag."""
        return await self._accessor("is_bot", value)

    # ── peers (peer lookups are what user-ID resolution runs on) ── #

    async def update_peers(
        self, peers: Iterable[tuple[int, int, str, str | None]]
    ) -> None:
        """Upsert peers; delegates to the module-level helper."""
        return await update_peers(self, peers)

    async def update_usernames(
        self, usernames: Iterable[tuple[int, list[str | None]]]
    ) -> None:
        """Replace peer username lists; delegates to the module-level helper."""
        return await update_usernames(self, usernames)

    async def get_peer_by_id(self, peer_id: int) -> Any:
        """Return the InputPeer; delegates to the module-level helper."""
        return await get_peer_by_id(self, peer_id)

    async def get_peer_by_username(self, username: str) -> Any:
        """Return the freshest InputPeer; delegates to the module-level helper."""
        return await get_peer_by_username(self, username)

    async def get_peer_by_phone_number(self, phone_number: str) -> Any:
        """Return the InputPeer; delegates to the module-level helper."""
        return await get_peer_by_phone_number(self, phone_number)

    # ── update states ── #

    async def get_update_states(
        self, ids: int | Iterable[int] | None = None
    ) -> list[UpdateState]:
        """Return stored update states oldest-first, optionally filtered by ID."""
        stmt = select(
            mtproto_state.c.id,
            mtproto_state.c.pts,
            mtproto_state.c.qts,
            mtproto_state.c.date,
            mtproto_state.c.seq,
        ).where(mtproto_state.c.id.like(f"{self._ns_like}:ustate:%"))
        if ids is not None:
            state_ids = (ids,) if isinstance(ids, int) else tuple(ids)
            if not state_ids:
                return []
            stmt = stmt.where(
                mtproto_state.c.id.in_([self._ustate(i) for i in state_ids])
            )
        docs = await db_call(
            lambda: fetch_all(stmt.order_by(mtproto_state.c.date.asc()))
        )
        return [
            UpdateState(
                int(str(d["id"]).rsplit(":", 1)[1]),
                d.get("pts"),
                d.get("qts"),
                d.get("date"),
                d.get("seq"),
            )
            for d in docs
        ]

    async def set_update_state(
        self, update_state: UpdateState | Iterable[UpdateState]
    ) -> None:
        """Merge update states, leaving stored fields intact when the new ones are None.

        Retries on transient write failures so Pyrogram's background
        ``handle_updates()`` task does not crash during a failover.
        """
        states = (
            [update_state] if isinstance(update_state, UpdateState) else update_state
        )
        rows = _update_state_rows(self, states)
        if not rows:
            return
        await _retry_write(
            lambda: _write_rows(rows, _update_state_upsert), timeout=_BATCH_TIMEOUT_S
        )

    async def delete_update_state(self, state_id: int | Iterable[int]) -> None:
        """Delete update states by ID with transient-error retry."""
        state_ids = (state_id,) if isinstance(state_id, int) else tuple(state_id)
        ustate_ids = [self._ustate(i) for i in state_ids]

        await _retry_write(
            lambda: run(
                mtproto_state.delete().where(mtproto_state.c.id.in_(ustate_ids))
            )
        )

    # ── single-owner lease ── #
    # * One live MTProto connection per shared session: Telegram kills the
    # * auth key when two clients connect with it at once
    # * (406 AUTH_KEY_DUPLICATED), so fleet instances elect exactly one
    # * owner before connecting. The lease row lives in this same
    # * table; a crashed holder fails over after at most one TTL.

    def _lease_id(self) -> str:
        """Build the row ID for the single-owner lease."""
        return f"{self._ns}:lock:mtproto_owner"

    async def claim_owner(self, owner: str, *, ttl_s: float) -> bool:
        """Claim the single-owner lease; delegates to the module-level helper."""
        return await claim_owner(self, owner, ttl_s=ttl_s)

    async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
        """Renew the lease; delegates to the module-level helper."""
        return await refresh_owner(self, owner, ttl_s=ttl_s)

    async def release_owner(self, owner: str) -> None:
        """Release the lease; delegates to the module-level helper."""
        return await release_owner(self, owner)
