# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.kicks_db."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.database import kicks_db


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length=None) -> list[dict]:
        return list(self._docs)


class FakeKicksCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = [dict(d) for d in (docs or [])]
        self._next_id = 1

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        stored = dict(doc)
        stored["_id"] = self._next_id
        self._next_id += 1
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for d in self.docs if all(d.get(k) == v for k, v in flt.items()))

    def find(self, flt: dict, sort=None) -> FakeCursor:
        matched = [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]
        if sort:
            for key, direction in reversed(sort):
                matched.sort(key=lambda d: d.get(key, 0), reverse=direction < 0)
        return FakeCursor(matched)


class TestLogKick:
    async def test_inserts_record(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(101, 201, "spam", 999)
        assert len(fake.docs) == 1

    async def test_record_fields(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(101, 201, "flood", 999)
        doc = fake.docs[0]
        assert doc["user_id"] == 101
        assert doc["chat_id"] == 201
        assert doc["reason"] == "flood"
        assert doc["admin_id"] == 999
        assert "timestamp" in doc

    async def test_multiple_kicks_accumulated(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(1, 10, "r1", 9)
        await kicks_db.log_kick(2, 20, "r2", 9)
        assert len(fake.docs) == 2


class TestUserKicks:
    async def test_empty_returns_list(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        result = await kicks_db.user_kicks(42)
        assert result == []

    async def test_returns_matching_records(self, monkeypatch):
        docs = [
            {
                "user_id": 42,
                "chat_id": 1,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 6, 2, tzinfo=timezone.utc),
            },
            {
                "user_id": 99,
                "chat_id": 1,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 6, 1, tzinfo=timezone.utc),
            },
        ]
        fake = FakeKicksCollection(docs)
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        result = await kicks_db.user_kicks(42)
        assert len(result) == 1
        assert result[0]["user_id"] == 42

    async def test_sorted_newest_first(self, monkeypatch):
        docs = [
            {
                "user_id": 42,
                "chat_id": 1,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
            {
                "user_id": 42,
                "chat_id": 2,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 6, 1, tzinfo=timezone.utc),
            },
        ]
        fake = FakeKicksCollection(docs)
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        result = await kicks_db.user_kicks(42)
        assert result[0]["timestamp"] > result[1]["timestamp"]


class TestUserKickCount:
    async def test_zero_when_none(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        assert await kicks_db.user_kick_count(42) == 0

    async def test_counts_only_matching_user(self, monkeypatch):
        docs = [
            {
                "user_id": 42,
                "chat_id": 1,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 1, 1),
            },
            {
                "user_id": 42,
                "chat_id": 2,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 2, 1),
            },
            {
                "user_id": 99,
                "chat_id": 1,
                "reason": "r",
                "admin_id": 9,
                "timestamp": datetime(2024, 1, 1),
            },
        ]
        fake = FakeKicksCollection(docs)
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        assert await kicks_db.user_kick_count(42) == 2
        assert await kicks_db.user_kick_count(99) == 1


class TestLogKickTimestamp:
    async def test_timestamp_is_datetime(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(10, 20, "reason", 99)
        doc = fake.docs[0]
        assert isinstance(doc["timestamp"], datetime)

    async def test_admin_id_recorded_correctly(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(10, 20, "reason", 555)
        assert fake.docs[0]["admin_id"] == 555

    async def test_reason_stored_as_is(self, monkeypatch):
        fake = FakeKicksCollection()
        monkeypatch.setattr(kicks_db, "_kicks", lambda: fake)
        await kicks_db.log_kick(10, 20, "custom reason text", 9)
        assert fake.docs[0]["reason"] == "custom reason text"
