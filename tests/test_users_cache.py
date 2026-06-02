# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.users_cache."""

from __future__ import annotations

from types import SimpleNamespace

from tcbot.database import users_cache


def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(k) == v for k, v in flt.items())


class FakeSortCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "FakeSortCursor":
        self._docs = sorted(
            self._docs,
            key=lambda d: d.get(key) or "",
            reverse=direction < 0,
        )
        return self

    async def to_list(self, length=None) -> list[dict]:
        return list(self._docs)


class FakeCacheColl:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = [dict(d) for d in (docs or [])]
        self._upsert_calls: list[tuple] = []

    async def update_one(
        self, flt: dict, update: dict, *, upsert: bool = False
    ) -> SimpleNamespace:
        self._upsert_calls.append((flt, update))
        for d in self.docs:
            if _matches(d, flt):
                if "$set" in update:
                    d.update(update["$set"])
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            new_doc = dict(flt)
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            self.docs.append(new_doc)
        return SimpleNamespace(matched_count=0, upserted_id=None)

    async def find_one(self, flt: dict, projection=None) -> dict | None:
        for d in self.docs:
            if _matches(d, flt):
                return d
        return None

    def find(self, flt: dict, projection=None) -> "FakeSortCursor":
        matched = [d for d in self.docs if _matches(d, flt)]
        return FakeSortCursor(matched)

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for d in self.docs if _matches(d, flt))


class TestUpsertUser:
    async def test_inserts_new_user(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        await users_cache.upsert_user(42, "alice", "Alice")
        assert len(fake._upsert_calls) == 1

    async def test_updates_existing_user(self, monkeypatch):
        docs = [{"user_id": 42, "first_name": "Old", "username": None}]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        await users_cache.upsert_user(42, "alice", "New")
        assert fake.docs[0]["first_name"] == "New"


class TestGetUser:
    async def test_returns_none_when_missing(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        assert await users_cache.get_user(99) is None

    async def test_returns_full_doc(self, monkeypatch):
        docs = [{"user_id": 42, "first_name": "Alice", "username": "alice"}]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_user(42)
        assert result is not None
        assert result["first_name"] == "Alice"


class TestGetUserMentionData:
    async def test_returns_fallback_when_missing(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        fname, uname = await users_cache.get_user_mention_data(99)
        assert fname == "User 99"
        assert uname is None

    async def test_returns_name_and_username(self, monkeypatch):
        docs = [{"user_id": 42, "first_name": "Alice", "username": "alice"}]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        fname, uname = await users_cache.get_user_mention_data(42)
        assert fname == "Alice"
        assert uname == "alice"

    async def test_username_can_be_none(self, monkeypatch):
        docs = [{"user_id": 42, "first_name": "Alice", "username": None}]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        fname, uname = await users_cache.get_user_mention_data(42)
        assert fname == "Alice"
        assert uname is None


class TestGetMentionDataBatch:
    async def test_empty_returns_empty(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_mention_data_batch([])
        assert result == {}

    async def test_returns_known_users(self, monkeypatch):
        docs = [
            {"user_id": 1, "first_name": "Alice", "username": "alice"},
            {"user_id": 2, "first_name": "Bob", "username": None},
        ]

        class FakeBatchColl(FakeCacheColl):
            def find(self, flt: dict, projection=None):
                user_ids = flt.get("user_id", {}).get("$in", [])
                matched = [d for d in self.docs if d.get("user_id") in user_ids]
                return FakeSortCursor(matched)

        fake2 = FakeBatchColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake2)
        result = await users_cache.get_mention_data_batch([1, 2])
        assert result[1] == ("Alice", "alice")
        assert result[2] == ("Bob", None)

    async def test_missing_users_get_defaults(self, monkeypatch):
        class FakeBatchColl(FakeCacheColl):
            def find(self, flt: dict, projection=None):
                return FakeSortCursor([])

        fake2 = FakeBatchColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake2)
        result = await users_cache.get_mention_data_batch([99, 100])
        assert result[99] == ("User 99", None)
        assert result[100] == ("User 100", None)


class TestGetFirstNamessBatch:
    async def test_empty_returns_empty(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_first_names_batch([])
        assert result == {}

    async def test_missing_users_get_defaults(self, monkeypatch):
        class FakeBatchColl(FakeCacheColl):
            def find(self, flt: dict, projection=None):
                return FakeSortCursor([])

        fake = FakeBatchColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_first_names_batch([5, 6])
        assert result[5] == "User 5"
        assert result[6] == "User 6"


class TestGetFirstName:
    async def test_returns_fallback_when_missing(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_first_name(42, "Unknown")
        assert result == "Unknown"

    async def test_returns_cached_name(self, monkeypatch):
        docs = [{"user_id": 42, "first_name": "Alice"}]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_first_name(42, "Unknown")
        assert result == "Alice"

    async def test_empty_fallback_default(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        result = await users_cache.get_first_name(42)
        assert result == ""


class TestTotalUsers:
    async def test_zero_when_empty(self, monkeypatch):
        fake = FakeCacheColl()
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        assert await users_cache.total_users() == 0

    async def test_counts_all(self, monkeypatch):
        docs = [{"user_id": i, "first_name": f"U{i}"} for i in range(5)]
        fake = FakeCacheColl(docs)
        monkeypatch.setattr(users_cache, "col", lambda _: fake)
        assert await users_cache.total_users() == 5
