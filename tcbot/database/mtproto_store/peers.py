# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto store peers: upserts and lookups backing user-ID resolution."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pyrogram.storage.sqlite_storage import SQLiteStorage, get_input_peer

from tcbot.database.mongos import db_call

from .retry import _retry_write

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    from tcbot.database.mtproto_store.storage import MongoStorage


async def update_peers(
    store: MongoStorage, peers: Iterable[tuple[int, int, str, str | None]]
) -> None:
    """Upsert peers, preserving stored usernames like the usernames table does."""
    now = int(time.time())
    for peer_id, access_hash, peer_type, phone_number in peers:
        doc_id = store._peer(peer_id)

        async def _op(
            _did: str = doc_id,
            _ah: int = access_hash,
            _pt: str = peer_type,
            _pn: str | None = phone_number,
            _now: int = now,
        ) -> None:
            await db_call(
                store._coll().update_one(
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
    store: MongoStorage, usernames: Iterable[tuple[int, list[str | None]]]
) -> None:
    """Replace the username list of each given peer.

    Bumps ``updated_on`` alongside the names: username freshness is
    evaluated against that timestamp, so a names-only write must not
    leave the previous write time behind.
    """
    now = int(time.time())
    for peer_id, names in usernames:
        doc_id = store._peer(peer_id)
        filtered_names = [n for n in names if n is not None]

        async def _op(
            _did: str = doc_id,
            _names: list[str] = filtered_names,
            _now: int = now,
        ) -> None:
            await db_call(
                store._coll().update_one(
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


async def get_peer_by_id(store: MongoStorage, peer_id: int) -> Any:
    """Return the InputPeer for *peer_id*, or raise KeyError like SQLiteStorage."""
    doc = await db_call(store._coll().find_one({"_id": store._peer(peer_id)}))
    if doc is None:
        raise KeyError(f"ID not found: {peer_id}")
    return get_input_peer(peer_id, doc["access_hash"], doc["type"])


async def get_peer_by_username(store: MongoStorage, username: str) -> Any:
    """Return the freshest InputPeer for *username*, or raise KeyError."""
    doc = await db_call(
        store._coll().find_one(
            {"_id": {"$regex": f"^{store._ns_re}:peer:"}, "usernames": username},
            sort=[("updated_on", -1)],
        )
    )
    if doc is None:
        raise KeyError(f"Username not found: {username}")
    if abs(time.time() - doc.get("updated_on", 0)) > SQLiteStorage.USERNAME_TTL:
        raise KeyError(f"Username expired: {username}")
    peer_id = int(str(doc["_id"]).rsplit(":", 1)[1])
    return get_input_peer(peer_id, doc["access_hash"], doc["type"])


async def get_peer_by_phone_number(store: MongoStorage, phone_number: str) -> Any:
    """Return the InputPeer for *phone_number*, or raise KeyError."""
    doc = await db_call(
        store._coll().find_one(
            {
                "_id": {"$regex": f"^{store._ns_re}:peer:"},
                "phone_number": phone_number,
            }
        )
    )
    if doc is None:
        raise KeyError(f"Phone number not found: {phone_number}")
    peer_id = int(str(doc["_id"]).rsplit(":", 1)[1])
    return get_input_peer(peer_id, doc["access_hash"], doc["type"])
