# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Regression tests for the warnings database helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.database import warns_db


def _matches(doc: dict, flt: dict) -> bool:
    for key, expected in flt.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            if "$gt" in expected and not (
                value is not None and value > expected["$gt"]
            ):
                return False
            continue
        if value != expected:
            return False
    return True


def _sort_docs(docs: list[dict], sort: list[tuple[str, int]] | None) -> list[dict]:
    result = list(docs)
    if not sort:
        return result
    for key, direction in reversed(sort):
        result.sort(key=lambda doc: doc.get(key), reverse=direction < 0)
    return result


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return list(self._docs)


class FakeWarnsCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [dict(doc) for doc in docs or []]
        self._next_id = max([doc.get("_id", 0) for doc in self.docs], default=0) + 1

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        stored = dict(doc)
        stored["_id"] = self._next_id
        self._next_id += 1
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def delete_many(self, flt: dict) -> SimpleNamespace:
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, flt)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for doc in self.docs if _matches(doc, flt))

    async def find_one(self, flt: dict, sort: list[tuple[str, int]] | None = None):
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return docs[0] if docs else None

    async def delete_one(self, flt: dict) -> SimpleNamespace:
        for idx, doc in enumerate(self.docs):
            if _matches(doc, flt):
                del self.docs[idx]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def find(self, flt: dict, sort: list[tuple[str, int]] | None = None) -> FakeCursor:
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return FakeCursor(docs)


class FakeWarnCountsCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = {(doc["user_id"], doc["chat_id"]): dict(doc) for doc in docs or []}

    def _key(self, flt: dict) -> tuple[int, int]:
        return int(flt["user_id"]), int(flt["chat_id"])

    def _match(self, doc: dict, flt: dict) -> bool:
        return _matches(doc, flt)

    async def find_one(self, flt: dict, projection=None):
        return self.docs.get(self._key(flt))

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        key = self._key(flt)
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, modified_count=0)
            doc = {"user_id": key[0], "chat_id": key[1], "count": 0}
        if "$setOnInsert" in update and key not in self.docs:
            doc.update(update["$setOnInsert"])
        if "$set" in update:
            doc.update(update["$set"])
        if "$inc" in update:
            doc["count"] = int(doc.get("count", 0)) + int(update["$inc"]["count"])
        self.docs[key] = doc
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def find_one_and_update(
        self,
        flt: dict,
        update: dict,
        upsert: bool = False,
        return_document=None,
        projection=None,
    ):
        key = self._key(flt)
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return None
            doc = {"user_id": key[0], "chat_id": key[1], "count": 0}
        if not self._match(doc, flt):
            return None
        if "$setOnInsert" in update and key not in self.docs:
            doc.update(update["$setOnInsert"])
        if "$set" in update:
            doc.update(update["$set"])
        if "$inc" in update:
            doc["count"] = int(doc.get("count", 0)) + int(update["$inc"]["count"])
        self.docs[key] = doc
        return dict(doc)

    async def delete_one(self, flt: dict) -> SimpleNamespace:
        key = self._key(flt)
        if key in self.docs:
            del self.docs[key]
            return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


def _patch_collections(
    monkeypatch, warns: FakeWarnsCollection, counts: FakeWarnCountsCollection
) -> None:
    monkeypatch.setattr(warns_db, "_warns", lambda: warns)
    monkeypatch.setattr(warns_db, "_warn_counts", lambda: counts)


async def test_add_warn_uses_atomic_counter(monkeypatch) -> None:
    warns = FakeWarnsCollection()
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    first = await warns_db.add_warn(100, "reason 1", 1, 10)
    second = await warns_db.add_warn(100, "reason 2", 1, 10)

    assert first == 1
    assert second == 2
    assert counts.docs[(100, 10)]["count"] == 2
    assert len(warns.docs) == 2


async def test_warn_count_backfills_and_clear_removes_counter(monkeypatch) -> None:
    warns = FakeWarnsCollection(
        [
            {
                "_id": 1,
                "user_id": 200,
                "reason": "first",
                "admin_id": 1,
                "chat_id": 20,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 2,
                "user_id": 200,
                "reason": "second",
                "admin_id": 1,
                "chat_id": 20,
                "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    count = await warns_db.warn_count(200, 20)
    assert count == 2
    assert counts.docs[(200, 20)]["count"] == 2

    removed = await warns_db.clear_warns(200, 20)
    assert removed == 2
    assert warns.docs == []
    assert (200, 20) not in counts.docs


async def test_remove_last_warn_decrements_counter(monkeypatch) -> None:
    warns = FakeWarnsCollection(
        [
            {
                "_id": 1,
                "user_id": 300,
                "reason": "older",
                "admin_id": 1,
                "chat_id": 30,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 2,
                "user_id": 300,
                "reason": "newer",
                "admin_id": 1,
                "chat_id": 30,
                "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection([{"user_id": 300, "chat_id": 30, "count": 2}])
    _patch_collections(monkeypatch, warns, counts)

    removed = await warns_db.remove_last_warn(300, 30)
    assert removed is True
    assert len(warns.docs) == 1
    assert warns.docs[0]["reason"] == "older"
    assert counts.docs[(300, 30)]["count"] == 1
