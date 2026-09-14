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

import logging
import time
from typing import TYPE_CHECKING

from pyrogram.storage import Storage, UpdateState
from pyrogram.storage.sqlite_storage import SQLiteStorage, get_input_peer

from tcbot.database.mongos import col, db_call

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

log = logging.getLogger(__name__)


class MongoStorage(Storage):
    """Kurigram :class:`Storage` persisted in the ``mtproto_state`` collection."""

    def __init__(self, namespace: str) -> None:
        """Scope every key under *namespace* so sessions never collide."""
        self._ns = namespace

    # ── key helpers ── #

    def _coll(self):  # type: ignore[no-untyped-def]
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
        """Drop every document in this namespace."""
        await db_call(self._coll().delete_many({"_id": {"$regex": f"^{self._ns}:"}}))

    # ── scalar accessors (same object-sentinel contract as SQLiteStorage) ── #

    async def _get_scalar(self, name: str) -> Any:
        """Read scalar *name*, or None when never written."""
        doc = await db_call(self._coll().find_one({"_id": self._kv(name)}))
        return doc["value"] if doc else None

    async def _set_scalar(self, name: str, value: Any) -> None:
        """Upsert scalar *name*."""
        await db_call(
            self._coll().replace_one(
                {"_id": self._kv(name)}, {"value": value}, upsert=True
            )
        )

    def _accessor(  # type: ignore[no-untyped-def]
        self, name: str, value: Any = object
    ):
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
            await db_call(
                self._coll().update_one(
                    {"_id": self._peer(peer_id)},
                    {
                        "$set": {
                            "access_hash": access_hash,
                            "type": peer_type,
                            "phone_number": phone_number,
                            "updated_on": now,
                        },
                        "$setOnInsert": {"usernames": []},
                    },
                    upsert=True,
                )
            )

    async def update_usernames(
        self, usernames: Iterable[tuple[int, list[str | None]]]
    ) -> None:
        """Replace the username list of each given peer."""
        for peer_id, names in usernames:
            await db_call(
                self._coll().update_one(
                    {"_id": self._peer(peer_id)},
                    {"$set": {"usernames": [n for n in names if n is not None]}},
                    upsert=True,
                )
            )

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
                {"_id": {"$regex": f"^{self._ns}:peer:"}, "usernames": username},
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
                {"_id": {"$regex": f"^{self._ns}:peer:"}, "phone_number": phone_number}
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
        filt: dict[str, Any] = {"_id": {"$regex": f"^{self._ns}:ustate:"}}
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
        """Merge update states, leaving stored fields intact when the new ones are None."""
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
                await db_call(
                    self._coll().update_one(
                        {"_id": self._ustate(state.id)}, {"$set": patch}, upsert=True
                    )
                )

    async def delete_update_state(self, state_id: int | Iterable[int]) -> None:
        """Delete update states by ID."""
        state_ids = (state_id,) if isinstance(state_id, int) else tuple(state_id)
        await db_call(
            self._coll().delete_many(
                {"_id": {"$in": [self._ustate(i) for i in state_ids]}}
            )
        )
