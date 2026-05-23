# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Regression tests for deterministic active-ban reads.
"""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database import bans_db


def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(key) == value for key, value in flt.items())


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


class FakeBansCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    async def find_one(self, flt: dict, projection=None, sort=None):
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return docs[0] if docs else None

    def find(self, flt: dict, projection=None, sort=None) -> FakeCursor:
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return FakeCursor(docs)


async def test_get_active_ban_prefers_newest_duplicate(monkeypatch) -> None:
    docs = [
        {
            "ban_id": "old",
            "banned_user_id": 42,
            "is_active": True,
            "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
        },
        {
            "ban_id": "new",
            "banned_user_id": 42,
            "is_active": True,
            "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
        },
    ]
    fake = FakeBansCollection(docs)
    monkeypatch.setattr(bans_db, "_bans", lambda: fake)

    ban = await bans_db.get_active_ban(42)

    assert ban is not None
    assert ban["ban_id"] == "new"


async def test_active_bans_returns_newest_first(monkeypatch) -> None:
    docs = [
        {
            "ban_id": "old",
            "banned_user_id": 1,
            "is_active": True,
            "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
        },
        {
            "ban_id": "new",
            "banned_user_id": 2,
            "is_active": True,
            "timestamp": datetime(2025, 1, 3, tzinfo=timezone.utc),
        },
        {
            "ban_id": "mid",
            "banned_user_id": 3,
            "is_active": True,
            "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
        },
    ]
    fake = FakeBansCollection(docs)
    monkeypatch.setattr(bans_db, "_bans", lambda: fake)

    active = await bans_db.active_bans()

    assert [doc["ban_id"] for doc in active] == ["new", "mid", "old"]
