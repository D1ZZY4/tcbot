# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.queues_db."""

from __future__ import annotations

from types import SimpleNamespace

from tcbot.database import queues_db


def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(k) == v for k, v in flt.items())


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length=None) -> list[dict]:
        return list(self._docs)


class FakeRequestsCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = [dict(d) for d in (docs or [])]

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        stored = dict(doc)
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored.get("request_id"))

    async def find_one(self, flt: dict) -> dict | None:
        for d in self.docs:
            if _matches(d, flt):
                return d
        return None

    def find(self, flt: dict) -> FakeCursor:
        return FakeCursor([d for d in self.docs if _matches(d, flt)])

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for d in self.docs if _matches(d, flt))

    async def update_one(self, flt: dict, update: dict) -> SimpleNamespace:
        for d in self.docs:
            if _matches(d, flt):
                if "$set" in update:
                    d.update(update["$set"])
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


class TestEnqueue:
    async def test_returns_request_id(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        monkeypatch.setattr(queues_db, "_new_request_id", lambda: "abc123")
        result = await queues_db.enqueue(101, "user", "Alice", 999)
        assert result == "abc123"

    async def test_inserts_document(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        monkeypatch.setattr(queues_db, "_new_request_id", lambda: "id001")
        await queues_db.enqueue(101, "user", "Alice", 999)
        assert len(fake.docs) == 1

    async def test_document_fields(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        monkeypatch.setattr(queues_db, "_new_request_id", lambda: "id001")
        await queues_db.enqueue(101, "alice_handle", "Alice", 999)
        doc = fake.docs[0]
        assert doc["target_id"] == 101
        assert doc["username"] == "alice_handle"
        assert doc["first_name"] == "Alice"
        assert doc["promoted_by"] == 999
        assert doc["status"] == "pending"
        assert doc["request_id"] == "id001"
        assert doc["resolved_date"] is None
        assert doc["resolved_by"] is None

    async def test_username_can_be_none(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        monkeypatch.setattr(queues_db, "_new_request_id", lambda: "id001")
        await queues_db.enqueue(101, None, "Alice", 999)
        assert fake.docs[0]["username"] is None


class TestGetRequestById:
    async def test_returns_none_when_missing(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.get_request_by_id("nope") is None

    async def test_returns_matching_doc(self, monkeypatch):
        docs = [{"request_id": "abc", "target_id": 1, "status": "pending"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        result = await queues_db.get_request_by_id("abc")
        assert result is not None
        assert result["request_id"] == "abc"

    async def test_does_not_return_wrong_id(self, monkeypatch):
        docs = [{"request_id": "abc", "target_id": 1, "status": "pending"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.get_request_by_id("xyz") is None


class TestGetRequest:
    async def test_returns_none_when_no_pending(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.get_request(42) is None

    async def test_returns_pending_for_user(self, monkeypatch):
        docs = [{"request_id": "r1", "target_id": 42, "status": "pending"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        result = await queues_db.get_request(42)
        assert result is not None
        assert result["target_id"] == 42

    async def test_ignores_resolved_requests(self, monkeypatch):
        docs = [{"request_id": "r1", "target_id": 42, "status": "approved"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.get_request(42) is None


class TestAllPending:
    async def test_empty(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.all_pending() == []

    async def test_returns_pending_only(self, monkeypatch):
        docs = [
            {"request_id": "r1", "target_id": 1, "status": "pending"},
            {"request_id": "r2", "target_id": 2, "status": "approved"},
            {"request_id": "r3", "target_id": 3, "status": "pending"},
        ]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        result = await queues_db.all_pending()
        assert len(result) == 2
        assert all(r["status"] == "pending" for r in result)


class TestResolve:
    async def test_updates_status(self, monkeypatch):
        docs = [{"request_id": "r1", "target_id": 1, "status": "pending"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        await queues_db.resolve("r1", "approved", 999)
        assert fake.docs[0]["status"] == "approved"
        assert fake.docs[0]["resolved_by"] == 999

    async def test_sets_resolved_date(self, monkeypatch):
        docs = [{"request_id": "r1", "target_id": 1, "status": "pending"}]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        await queues_db.resolve("r1", "rejected", 999)
        assert fake.docs[0]["resolved_date"] is not None


class TestPendingCount:
    async def test_zero_when_empty(self, monkeypatch):
        fake = FakeRequestsCollection()
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.pending_count() == 0

    async def test_counts_pending_only(self, monkeypatch):
        docs = [
            {"request_id": "r1", "status": "pending"},
            {"request_id": "r2", "status": "approved"},
            {"request_id": "r3", "status": "pending"},
        ]
        fake = FakeRequestsCollection(docs)
        monkeypatch.setattr(queues_db, "_requests", lambda: fake)
        assert await queues_db.pending_count() == 2
