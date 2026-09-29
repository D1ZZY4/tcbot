# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB-backed Kurigram storage engine for the shared MTProto session."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from pyrogram.storage import Storage, UpdateState

from tcbot.database import mtproto_store as _store_pkg
from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger

from .lease import claim_owner as _claim_owner
from .lease import refresh_owner as _refresh_owner
from .lease import release_owner as _release_owner
from .peers import get_peer_by_id as _get_peer_by_id
from .peers import get_peer_by_phone_number as _get_peer_by_phone_number
from .peers import get_peer_by_username as _get_peer_by_username
from .peers import update_peers as _update_peers
from .peers import update_usernames as _update_usernames
from .retry import _retry_write

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable
    from typing import Any

    from motor.motor_asyncio import AsyncIOMotorCollection

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto_store")


class MongoStorage(Storage):
    """Kurigram :class:`Storage` persisted in the ``mtproto_state`` collection.

    Semantics mirror Kurigram's ``SQLiteStorage`` exactly (same KeyError
    misses, same 8h username TTL, same COALESCE-style update-state merge);
    only the backend differs.
    """

    def __init__(self, namespace: str) -> None:
        """Scope every key under *namespace* so sessions never collide."""
        self._ns = namespace
        # * Pre-escaped once: the namespace feeds several anchored $regex
        # * filters below, and an unescaped metacharacter there would widen
        # * every peer/username/state scan past this session's keys.
        self._ns_re = re.escape(namespace)

    # ── key helpers ── #
    # * Collection ``mtproto_state``, one document per key, scoped by
    # * namespace: ``<ns>:kv:<name>`` scalars, ``<ns>:peer:<peer_id>``
    # * peers, ``<ns>:ustate:<id>`` update states.

    def _coll(self) -> AsyncIOMotorCollection:
        """Return the shared state collection."""
        # * Resolved via the package namespace so patching
        # * tcbot.database.mtproto_store.col keeps working as before.
        return _store_pkg.col("mtproto_state")

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
        """Upsert peers; delegates to peers.update_peers (single owner)."""
        return await _update_peers(self, peers)

    async def update_usernames(
        self, usernames: Iterable[tuple[int, list[str | None]]]
    ) -> None:
        """Replace peer username lists; delegates to peers.update_usernames."""
        return await _update_usernames(self, usernames)

    async def get_peer_by_id(self, peer_id: int) -> Any:
        """Return the InputPeer; delegates to peers.get_peer_by_id."""
        return await _get_peer_by_id(self, peer_id)

    async def get_peer_by_username(self, username: str) -> Any:
        """Return the freshest InputPeer; delegates to peers.get_peer_by_username."""
        return await _get_peer_by_username(self, username)

    async def get_peer_by_phone_number(self, phone_number: str) -> Any:
        """Return the InputPeer; delegates to peers.get_peer_by_phone_number."""
        return await _get_peer_by_phone_number(self, phone_number)

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

    # ── single-owner lease ── #
    # * One live MTProto connection per shared session: Telegram kills the
    # * auth key when two clients connect with it at once
    # * (406 AUTH_KEY_DUPLICATED), so fleet instances elect exactly one
    # * owner before connecting. The lease row lives in this same
    # * collection; a crashed holder fails over after at most one TTL.

    def _lease_id(self) -> str:
        """Build the document ID for the single-owner lease."""
        return f"{self._ns}:lock:mtproto_owner"

    async def claim_owner(self, owner: str, *, ttl_s: float) -> bool:
        """Claim the single-owner lease; delegates to lease.claim_owner."""
        return await _claim_owner(self, owner, ttl_s=ttl_s)

    async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
        """Renew the lease; delegates to lease.refresh_owner."""
        return await _refresh_owner(self, owner, ttl_s=ttl_s)

    async def release_owner(self, owner: str) -> None:
        """Release the lease; delegates to lease.release_owner."""
        return await _release_owner(self, owner)
