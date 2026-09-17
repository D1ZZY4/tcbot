# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB-backed Kurigram storage engine: the MTProto session lives in the database.

One shared session for the whole fleet: ephemeral runners and the beta host
read the same auth key, peers, and update states. Semantics mirror Kurigram's
``SQLiteStorage`` exactly (same KeyError misses, same 8h username TTL, same
COALESCE-style update-state merge); only the backend differs.

Collection ``mtproto_state``, one document per key, all scoped by namespace::

    {_id: "<ns>:kv:<name>", value: ...}
    {_id: "<ns>:peer:<peer_id>", access_hash, type, phone_number, usernames, updated_on}
    {_id: "<ns>:ustate:<id>", pts, qts, date, seq}
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

from pymongo.errors import WriteConcernError
from pyrogram.storage import Storage, UpdateState
from pyrogram.storage.sqlite_storage import SQLiteStorage, get_input_peer

from tcbot.database.mongos import col, db_call
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from typing import Any

    from motor.motor_asyncio import AsyncIOMotorCollection

# * Maximum retries for transient write concern errors (e.g. replica set
# * failover). Each retry waits exponentially: 0.5s, 1s, 2s.
_MAX_WRITE_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 0.5

log = get_logger(__name__)


def _is_transient_write_error(exc: BaseException) -> bool:
    """Return True when *exc* is a retryable MongoDB write concern error."""
    return isinstance(exc, WriteConcernError) and "RetryableWriteError" in getattr(
        exc, "details", {}
    ).get("errorLabels", [])


async def _retry_write(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Execute a fresh coroutine from *coro_factory* with retries on transient WriteConcernError.

    Pyrogram's ``handle_updates()`` background task persists update states
    through this store.  A transient replica-set failover (code 11602 /
    ``InterruptedDueToReplStateChange``) raises ``WriteConcernError`` with
    the ``RetryableWriteError`` label.  Because the task is fire-and-forget,
    the exception is never retrieved and the event loop reports it as an
    unhandled task exception.

    Retrying transparently keeps the session alive through brief replica-set
    elections without flooding the error channel.

    *coro_factory* must return a **new** coroutine on each call so retries
    re-execute the operation instead of re-awaiting a spent coroutine.
    """
    last_exc: BaseException | None = None
    for attempt in range(_MAX_WRITE_RETRIES):
        try:
            return await coro_factory()
        except BaseException as exc:
            if not _is_transient_write_error(exc) or attempt == _MAX_WRITE_RETRIES - 1:
                raise
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


class MongoStorage(Storage):
    """Kurigram :class:`Storage` persisted in the ``mtproto_state`` collection."""

    def __init__(self, namespace: str) -> None:
        """Scope every key under *namespace* so sessions never collide."""
        self._ns = namespace
        # * Pre-escaped once: the namespace feeds several anchored $regex
        # * filters below, and an unescaped metacharacter there would widen
        # * every peer/username/state scan past this session's keys.
        self._ns_re = re.escape(namespace)

    # ── key helpers ── #

    def _coll(self) -> AsyncIOMotorCollection:
        """Return the shared state collection."""
        return col("mtproto_state")

    def _kv(self, name: str) -> str:
        """Build the document ID for scalar *name*."""
        return f"{self._ns}:kv:{name}"

    def _peer(self, peer_id: int) -> str:
        """Build the document ID for *peer_id*."""
        return f"{self._ns}:peer:{peer_id}"

    def _ustate(self, state_id: int) -> str:
        """Build the document ID for update state *state_id*."""
        return f"{self._ns}:ustate:{state_id}"

    # ── lifecycle ── #

    async def open(self) -> None:
        """No-op: MongoDB needs no schema setup, keys are created on first write."""
        return

    async def save(self) -> None:
        """Bump the stored date, mirroring SQLiteStorage.save()."""
        await self.date(int(time.time()))

    async def close(self) -> None:
        """No-op: Motor connections are owned by the shared client pool."""
        return

    async def delete(self) -> None:
        """Drop every document in this namespace with transient-error retry."""
        ns_re = self._ns_re

        async def _op() -> None:
            await db_call(self._coll().delete_many({"_id": {"$regex": f"^{ns_re}:"}}))

        await _retry_write(_op)

    # ── scalar accessors (same object-sentinel contract as SQLiteStorage) ── #

    async def _get_scalar(self, name: str) -> Any:
        """Read scalar *name*, or None when never written."""
        doc = await db_call(self._coll().find_one({"_id": self._kv(name)}))
        return doc["value"] if doc else None

    async def _set_scalar(self, name: str, value: Any) -> None:
        """Upsert scalar *name* with transient-error retry."""
        kv = self._kv(name)

        async def _op() -> None:
            await db_call(
                self._coll().replace_one({"_id": kv}, {"value": value}, upsert=True)
            )

        await _retry_write(_op)

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
        """Upsert peers, preserving stored usernames like the usernames table does."""
        now = int(time.time())
        for peer_id, access_hash, peer_type, phone_number in peers:
            doc_id = self._peer(peer_id)

            async def _op(
                _did: str = doc_id,
                _ah: int = access_hash,
                _pt: str = peer_type,
                _pn: str | None = phone_number,
                _now: int = now,
            ) -> None:
                await db_call(
                    self._coll().update_one(
                        {"_id": _did},
                        {
                            "$set": {
                                "access_hash": _ah,
                                "type": _pt,
                                "phone_number": _pn,
                                "updated_on": _now,
                            },
                            "$setOnInsert": {"usernames": []},
                        },
                        upsert=True,
                    )
                )

            await _retry_write(_op)

    async def update_usernames(
        self, usernames: Iterable[tuple[int, list[str | None]]]
    ) -> None:
        """Replace the username list of each given peer.

        Bumps ``updated_on`` alongside the names: username freshness is
        evaluated against that timestamp, so a names-only write must not
        leave the previous write time behind.
        """
        now = int(time.time())
        for peer_id, names in usernames:
            doc_id = self._peer(peer_id)
            filtered_names = [n for n in names if n is not None]

            async def _op(
                _did: str = doc_id,
                _names: list[str] = filtered_names,
                _now: int = now,
            ) -> None:
                await db_call(
                    self._coll().update_one(
                        {"_id": _did},
                        {
                            "$set": {
                                "usernames": _names,
                                "updated_on": _now,
                            }
                        },
                        upsert=True,
                    )
                )

            await _retry_write(_op)

    async def get_peer_by_id(self, peer_id: int) -> Any:
        """Return the InputPeer for *peer_id*, or raise KeyError like SQLiteStorage."""
        doc = await db_call(self._coll().find_one({"_id": self._peer(peer_id)}))
        if doc is None:
            raise KeyError(f"ID not found: {peer_id}")
        return get_input_peer(peer_id, doc["access_hash"], doc["type"])

    async def get_peer_by_username(self, username: str) -> Any:
        """Return the freshest InputPeer for *username*, or raise KeyError."""
        doc = await db_call(
            self._coll().find_one(
                {"_id": {"$regex": f"^{self._ns_re}:peer:"}, "usernames": username},
                sort=[("updated_on", -1)],
            )
        )
        if doc is None:
            raise KeyError(f"Username not found: {username}")
        if abs(time.time() - doc.get("updated_on", 0)) > SQLiteStorage.USERNAME_TTL:
            raise KeyError(f"Username expired: {username}")
        peer_id = int(str(doc["_id"]).rsplit(":", 1)[1])
        return get_input_peer(peer_id, doc["access_hash"], doc["type"])

    async def get_peer_by_phone_number(self, phone_number: str) -> Any:
        """Return the InputPeer for *phone_number*, or raise KeyError."""
        doc = await db_call(
            self._coll().find_one(
                {
                    "_id": {"$regex": f"^{self._ns_re}:peer:"},
                    "phone_number": phone_number,
                }
            )
        )
        if doc is None:
            raise KeyError(f"Phone number not found: {phone_number}")
        peer_id = int(str(doc["_id"]).rsplit(":", 1)[1])
        return get_input_peer(peer_id, doc["access_hash"], doc["type"])

    # ── update states ── #

    async def get_update_states(
        self, ids: int | Iterable[int] | None = None
    ) -> list[UpdateState]:
        """Return stored update states oldest-first, optionally filtered by ID."""
        filt: dict[str, Any] = {"_id": {"$regex": f"^{self._ns_re}:ustate:"}}
        if ids is not None:
            state_ids = (ids,) if isinstance(ids, int) else tuple(ids)
            if not state_ids:
                return []
            filt["_id"]["$in"] = [self._ustate(i) for i in state_ids]
        docs = await db_call(self._coll().find(filt).sort("date", 1).to_list(None))
        return [
            UpdateState(
                int(str(d["_id"]).rsplit(":", 1)[1]),
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

        Retries on transient ``WriteConcernError`` so Pyrogram's background
        ``handle_updates()`` task does not crash during replica-set elections.
        """
        states = (
            [update_state] if isinstance(update_state, UpdateState) else update_state
        )
        for state in states:
            patch = {
                k: v
                for k, v in (
                    ("pts", state.pts),
                    ("qts", state.qts),
                    ("date", state.date),
                    ("seq", state.seq),
                )
                if v is not None
            }
            if patch:
                state_id = state.id
                state_patch = dict(patch)

                async def _op(
                    _sid: int = state_id, _patch: dict[str, Any] = state_patch
                ) -> None:
                    await db_call(
                        self._coll().update_one(
                            {"_id": self._ustate(_sid)},
                            {"$set": _patch},
                            upsert=True,
                        )
                    )

                await _retry_write(_op)

    async def delete_update_state(self, state_id: int | Iterable[int]) -> None:
        """Delete update states by ID with transient-error retry."""
        state_ids = (state_id,) if isinstance(state_id, int) else tuple(state_id)
        ustate_ids = [self._ustate(i) for i in state_ids]

        async def _op() -> None:
            await db_call(self._coll().delete_many({"_id": {"$in": ustate_ids}}))

        await _retry_write(_op)
