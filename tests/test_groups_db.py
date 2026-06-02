# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.groups_db."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tcbot.database import groups_db
from tcbot.database.cache import active_groups_cache, connected_cache


def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(k) == v for k, v in flt.items())


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length=None) -> list[dict]:
        return list(self._docs)


class FakeGroupsColl:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = [dict(d) for d in (docs or [])]

    async def find_one(self, flt: dict, projection=None) -> dict | None:
        for d in self.docs:
            if _matches(d, flt):
                return d
        return None

    def find(self, flt: dict, projection=None) -> FakeCursor:
        return FakeCursor([d for d in self.docs if _matches(d, flt)])

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for d in self.docs if _matches(d, flt))

    async def update_one(
        self, flt: dict, update: dict, *, upsert: bool = False
    ) -> SimpleNamespace:
        for d in self.docs:
            if _matches(d, flt):
                if "$set" in update:
                    d.update(update["$set"])
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            new_doc = dict(flt)
            if "$set" in update:
                new_doc.update(update["$set"])
            self.docs.append(new_doc)
        return SimpleNamespace(matched_count=0, modified_count=0)


class FakePendingColl(FakeGroupsColl):
    async def delete_one(self, flt: dict) -> SimpleNamespace:
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


@pytest.fixture(autouse=True)
def clear_caches():
    connected_cache.clear()
    active_groups_cache.clear()
    yield
    connected_cache.clear()
    active_groups_cache.clear()


class TestGetGroup:
    async def test_returns_none_when_missing(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.get_group(12345) is None

    async def test_returns_matching_group(self, monkeypatch):
        docs = [{"chat_id": 12345, "title": "Test", "is_active": True}]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        result = await groups_db.get_group(12345)
        assert result is not None
        assert result["title"] == "Test"


class TestIsConnected:
    async def test_returns_false_when_not_connected(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.is_connected(12345) is False

    async def test_returns_true_for_active_group(self, monkeypatch):
        docs = [{"chat_id": 12345, "is_active": True}]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.is_connected(12345) is True

    async def test_returns_false_for_inactive_group(self, monkeypatch):
        docs = [{"chat_id": 12345, "is_active": False}]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.is_connected(12345) is False

    async def test_cache_hit_skips_db(self, monkeypatch):
        connected_cache.put(12345, True)
        call_count = 0

        class CountingColl(FakeGroupsColl):
            async def find_one(self, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                return None

        monkeypatch.setattr(groups_db, "_groups", lambda: CountingColl())
        result = await groups_db.is_connected(12345)
        assert result is True
        assert call_count == 0


class TestAddGroup:
    async def test_inserts_new_group(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        await groups_db.add_group(12345, "Test Group", 999)
        assert any(d["chat_id"] == 12345 for d in fake.docs)

    async def test_marks_group_active(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        await groups_db.add_group(12345, "Test Group", 999)
        doc = next(d for d in fake.docs if d["chat_id"] == 12345)
        assert doc["is_active"] is True

    async def test_updates_connected_cache(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        await groups_db.add_group(12345, "Test Group", 999)
        assert connected_cache.get(12345) is True


class TestDeactivateGroup:
    async def test_marks_group_inactive(self, monkeypatch):
        docs = [{"chat_id": 12345, "is_active": True}]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        result = await groups_db.deactivate_group(12345)
        assert result is True
        assert fake.docs[0]["is_active"] is False

    async def test_returns_false_when_not_found(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        result = await groups_db.deactivate_group(99999)
        assert result is False

    async def test_updates_connected_cache(self, monkeypatch):
        docs = [{"chat_id": 12345, "is_active": True}]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        await groups_db.deactivate_group(12345)
        assert connected_cache.get(12345) is False


class TestActiveGroups:
    async def test_returns_empty_when_none(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        result = await groups_db.active_groups()
        assert result == []

    async def test_returns_active_only(self, monkeypatch):
        docs = [
            {"chat_id": 1, "is_active": True},
            {"chat_id": 2, "is_active": False},
        ]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        result = await groups_db.active_groups()
        assert len(result) == 1
        assert result[0]["chat_id"] == 1


class TestActiveGroupCount:
    async def test_zero_when_empty(self, monkeypatch):
        fake = FakeGroupsColl()
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.active_group_count() == 0

    async def test_counts_active_only(self, monkeypatch):
        docs = [
            {"chat_id": 1, "is_active": True},
            {"chat_id": 2, "is_active": True},
            {"chat_id": 3, "is_active": False},
        ]
        fake = FakeGroupsColl(docs)
        monkeypatch.setattr(groups_db, "_groups", lambda: fake)
        assert await groups_db.active_group_count() == 2


class TestPendingJoins:
    async def test_add_pending(self, monkeypatch):
        fake = FakePendingColl()
        monkeypatch.setattr(groups_db, "_pending", lambda: fake)
        await groups_db.add_pending(12345, "Test", 999, 111)
        assert any(d["chat_id"] == 12345 for d in fake.docs)

    async def test_get_pending_returns_none_when_missing(self, monkeypatch):
        fake = FakePendingColl()
        monkeypatch.setattr(groups_db, "_pending", lambda: fake)
        assert await groups_db.get_pending(99) is None

    async def test_get_pending_returns_doc(self, monkeypatch):
        docs = [{"chat_id": 12345, "title": "Test", "owner_id": 999, "message_id": 111}]
        fake = FakePendingColl(docs)
        monkeypatch.setattr(groups_db, "_pending", lambda: fake)
        result = await groups_db.get_pending(12345)
        assert result is not None
        assert result["chat_id"] == 12345

    async def test_remove_pending(self, monkeypatch):
        docs = [{"chat_id": 12345, "title": "Test"}]
        fake = FakePendingColl(docs)
        monkeypatch.setattr(groups_db, "_pending", lambda: fake)
        await groups_db.remove_pending(12345)
        assert len(fake.docs) == 0
