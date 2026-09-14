# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoStorage: round-trips against an in-memory fake collection, no MongoDB."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import pytest
from pyrogram.storage import UpdateState

from tcbot.database import mtproto_store
from tcbot.database.mtproto_store import MongoStorage


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> _FakeCursor:
        self._docs = sorted(
            self._docs, key=lambda d: d.get(key, 0), reverse=direction < 0
        )
        return self

    async def to_list(self, _n: object) -> list[dict[str, Any]]:
        return list(self._docs)


class _FakeColl:
    """Minimal Motor collection double supporting exactly the operators used."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def _match(self, doc: dict[str, Any], filt: dict[str, Any]) -> bool:
        for key, cond in filt.items():
            value = doc.get(key)
            if isinstance(cond, dict):
                for op, operand in cond.items():
                    if op == "$regex":
                        if not re.search(operand, str(doc.get("_id", ""))):
                            return False
                    elif op == "$in" and value not in operand:
                        return False
            elif key == "usernames":
                if cond not in (value or []):
                    return False
            elif value != cond:
                return False
        return True

    async def find_one(
        self, filt: dict[str, Any], sort: list[tuple[str, int]] | None = None
    ) -> dict[str, Any] | None:
        cands = [d for d in self.docs.values() if self._match(d, filt)]
        if sort:
            cands.sort(key=lambda d: d.get(sort[0][0], 0), reverse=sort[0][1] < 0)
        return dict(cands[0]) if cands else None

    async def replace_one(
        self, filt: dict[str, Any], repl: dict[str, Any], *, upsert: bool = False
    ) -> None:
        for doc_id, doc in self.docs.items():
            if self._match(doc, filt):
                self.docs[doc_id] = {"_id": doc_id, **repl}
                return
        if upsert:
            doc_id = filt.get("_id", "")
            self.docs[doc_id] = {"_id": doc_id, **repl}

    async def update_one(
        self, filt: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> None:
        target = next(
            (doc_id for doc_id, doc in self.docs.items() if self._match(doc, filt)),
            None,
        )
        if target is None:
            if not upsert:
                return
            target = filt.get("_id", "")
            self.docs[target] = {"_id": target}
        doc = self.docs[target]
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key, value in update.get("$setOnInsert", {}).items():
            doc.setdefault(key, value)

    async def delete_many(self, filt: dict[str, Any]) -> None:
        for doc_id in [i for i, d in self.docs.items() if self._match(d, filt)]:
            del self.docs[doc_id]

    def find(self, filt: dict[str, Any]) -> _FakeCursor:
        return _FakeCursor(
            [dict(d) for d in self.docs.values() if self._match(d, filt)]
        )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> tuple[MongoStorage, _FakeColl]:
    fake = _FakeColl()
    monkeypatch.setattr(mtproto_store, "col", lambda _name: fake)
    return MongoStorage("test"), fake


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_scalar_roundtrip(store: tuple[MongoStorage, _FakeColl]) -> None:
    s, _ = store
    _run(s.auth_key(b"\x01\x02"))
    _run(s.user_id(7))

    assert _run(s.auth_key()) == b"\x01\x02"
    assert _run(s.user_id()) == 7
    assert _run(s.dc_id()) is None


def test_peers_roundtrip(store: tuple[MongoStorage, _FakeColl]) -> None:
    s, _ = store
    _run(s.update_peers([(42, 99, "user", None)]))
    _run(s.update_usernames([(42, ["ghost", None])]))

    peer = _run(s.get_peer_by_id(42))

    assert (peer.user_id, peer.access_hash) == (42, 99)
    assert _run(s.get_peer_by_username("ghost")).user_id == 42


def test_missing_peer_raises_keyerror(store: tuple[MongoStorage, _FakeColl]) -> None:
    s, _ = store

    with pytest.raises(KeyError):
        _run(s.get_peer_by_id(1))
    with pytest.raises(KeyError):
        _run(s.get_peer_by_username("nobody"))


def test_expired_username_raises_keyerror(
    store: tuple[MongoStorage, _FakeColl],
) -> None:
    s, fake = store
    _run(s.update_peers([(42, 99, "user", None)]))
    _run(s.update_usernames([(42, ["ghost"])]))
    fake.docs["test:peer:42"]["updated_on"] = int(time.time()) - 10 * 60 * 60

    with pytest.raises(KeyError):
        _run(s.get_peer_by_username("ghost"))


def test_update_states_merge_and_delete(store: tuple[MongoStorage, _FakeColl]) -> None:
    s, _ = store
    _run(s.set_update_state(UpdateState(0, 10, None, 5, 1)))
    _run(s.set_update_state(UpdateState(0, None, 20, None, None)))

    (merged,) = _run(s.get_update_states(0))
    assert (merged.pts, merged.qts, merged.date, merged.seq) == (10, 20, 5, 1)

    _run(s.delete_update_state(0))
    assert _run(s.get_update_states()) == []


def test_namespaces_do_not_leak(store: tuple[MongoStorage, _FakeColl]) -> None:
    s, fake = store
    other = MongoStorage("other")
    _run(s.user_id(7))
    _run(other.user_id(8))

    assert _run(s.user_id()) == 7
    assert _run(other.user_id()) == 8

    _run(s.delete())
    assert _run(s.user_id()) is None
    assert _run(other.user_id()) == 8
    assert len(fake.docs) == 1
