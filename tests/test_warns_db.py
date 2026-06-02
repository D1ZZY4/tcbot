# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Regression tests for the warnings database helpers."""

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

    def find(
        self, flt: dict, projection=None, sort: list[tuple[str, int]] | None = None
    ) -> FakeCursor:
        docs = [doc for doc in self.docs.values() if self._match(doc, flt)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda d: d.get(key, 0), reverse=direction < 0)
        return FakeCursor(docs)


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


async def test_remove_last_warn_no_warnings_returns_false(monkeypatch) -> None:
    """remove_last_warn returns False when there are no warns for the user/chat."""
    warns = FakeWarnsCollection()
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    removed = await warns_db.remove_last_warn(999, 99)

    assert removed is False


# ──────────────────── get_warns ─────────────────────── #


async def test_get_warns_returns_oldest_first(monkeypatch) -> None:
    """get_warns returns all warnings for the user/chat sorted oldest first."""
    warns = FakeWarnsCollection(
        [
            {
                "_id": 2,
                "user_id": 10,
                "reason": "newer",
                "admin_id": 1,
                "chat_id": 50,
                "timestamp": datetime(2025, 2, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 1,
                "user_id": 10,
                "reason": "older",
                "admin_id": 1,
                "chat_id": 50,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    result = await warns_db.get_warns(10, 50)

    assert len(result) == 2
    assert result[0]["reason"] == "older"
    assert result[1]["reason"] == "newer"


async def test_get_warns_empty_returns_empty_list(monkeypatch) -> None:
    """get_warns returns an empty list when there are no warns."""
    warns = FakeWarnsCollection()
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    result = await warns_db.get_warns(999, 99)

    assert result == []


async def test_get_warns_only_returns_for_matching_chat(monkeypatch) -> None:
    """get_warns filters by both user_id and chat_id."""
    warns = FakeWarnsCollection(
        [
            {
                "_id": 1,
                "user_id": 20,
                "reason": "in chat A",
                "admin_id": 1,
                "chat_id": 100,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 2,
                "user_id": 20,
                "reason": "in chat B",
                "admin_id": 1,
                "chat_id": 200,
                "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    result = await warns_db.get_warns(20, 100)

    assert len(result) == 1
    assert result[0]["reason"] == "in chat A"


# ──────────────────── Per-user history ─────────────────────── #


async def test_user_total_warns_counts_across_all_chats(monkeypatch) -> None:
    """user_total_warns counts all warn rows for the user regardless of chat."""
    warns = FakeWarnsCollection(
        [
            {
                "_id": 1,
                "user_id": 30,
                "reason": "a",
                "admin_id": 1,
                "chat_id": 10,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 2,
                "user_id": 30,
                "reason": "b",
                "admin_id": 1,
                "chat_id": 20,
                "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
            },
            {
                "_id": 3,
                "user_id": 99,
                "reason": "other",
                "admin_id": 1,
                "chat_id": 10,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    total = await warns_db.user_total_warns(30)

    assert total == 2


async def test_user_total_warns_zero_when_no_warns(monkeypatch) -> None:
    """user_total_warns returns 0 when the user has no warnings."""
    warns = FakeWarnsCollection()
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    total = await warns_db.user_total_warns(555)

    assert total == 0


async def test_user_warn_groups_returns_chats_with_active_warns(monkeypatch) -> None:
    """user_warn_groups returns (chat_id, count) pairs for chats with count > 0."""
    warns = FakeWarnsCollection()
    counts = FakeWarnCountsCollection(
        [
            {
                "user_id": 40,
                "chat_id": 10,
                "count": 2,
                "updated_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
            },
            {
                "user_id": 40,
                "chat_id": 20,
                "count": 1,
                "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "user_id": 40,
                "chat_id": 30,
                "count": 0,
                "updated_at": datetime(2025, 1, 3, tzinfo=timezone.utc),
            },
        ]
    )
    _patch_collections(monkeypatch, warns, counts)

    groups = await warns_db.user_warn_groups(40)

    assert len(groups) == 2
    chat_ids = {g[0] for g in groups}
    assert chat_ids == {10, 20}


async def test_user_all_warns_newest_first(monkeypatch) -> None:
    """user_all_warns returns all warns for the user across chats, newest first."""
    warns = FakeWarnsCollection(
        [
            {
                "_id": 1,
                "user_id": 50,
                "reason": "oldest",
                "admin_id": 1,
                "chat_id": 10,
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 2,
                "user_id": 50,
                "reason": "newest",
                "admin_id": 1,
                "chat_id": 20,
                "timestamp": datetime(2025, 3, 1, tzinfo=timezone.utc),
            },
            {
                "_id": 3,
                "user_id": 99,
                "reason": "other user",
                "admin_id": 1,
                "chat_id": 10,
                "timestamp": datetime(2025, 2, 1, tzinfo=timezone.utc),
            },
        ]
    )
    counts = FakeWarnCountsCollection()
    _patch_collections(monkeypatch, warns, counts)

    all_warns = await warns_db.user_all_warns(50)

    assert len(all_warns) == 2
    assert all_warns[0]["reason"] == "newest"
    assert all_warns[1]["reason"] == "oldest"
