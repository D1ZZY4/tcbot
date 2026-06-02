# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.mutes_db."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.database import mutes_db


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length=None) -> list[dict]:
        return list(self._docs)


class FakeMutesCollection:
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


class TestLogMute:
    async def test_inserts_record(self, monkeypatch):
        fake = FakeMutesCollection()
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        await mutes_db.log_mute(101, 201, "spam", 999)
        assert len(fake.docs) == 1

    async def test_record_fields(self, monkeypatch):
        fake = FakeMutesCollection()
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        await mutes_db.log_mute(101, 201, "flood", 999)
        doc = fake.docs[0]
        assert doc["user_id"] == 101
        assert doc["chat_id"] == 201
        assert doc["reason"] == "flood"
        assert doc["admin_id"] == 999
        assert "timestamp" in doc

    async def test_multiple_mutes_accumulated(self, monkeypatch):
        fake = FakeMutesCollection()
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        await mutes_db.log_mute(1, 10, "r1", 9)
        await mutes_db.log_mute(2, 20, "r2", 9)
        assert len(fake.docs) == 2


class TestUserMutes:
    async def test_empty_returns_list(self, monkeypatch):
        fake = FakeMutesCollection()
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        result = await mutes_db.user_mutes(42)
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
        fake = FakeMutesCollection(docs)
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        result = await mutes_db.user_mutes(42)
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
        fake = FakeMutesCollection(docs)
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        result = await mutes_db.user_mutes(42)
        assert result[0]["timestamp"] > result[1]["timestamp"]


class TestUserMuteCount:
    async def test_zero_when_none(self, monkeypatch):
        fake = FakeMutesCollection()
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        assert await mutes_db.user_mute_count(42) == 0

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
        fake = FakeMutesCollection(docs)
        monkeypatch.setattr(mutes_db, "_mutes", lambda: fake)
        assert await mutes_db.user_mute_count(42) == 2
        assert await mutes_db.user_mute_count(99) == 1
