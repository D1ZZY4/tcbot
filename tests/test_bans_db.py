# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for the bans database helpers — reads, mutations, statistics, and history."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tcbot.database import bans_db


def _matches(doc: dict, flt: dict) -> bool:
    """Simple filter matcher that handles basic equality and $ne/$exists operators."""
    for key, expected in flt.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$exists" in expected and (key in doc) != expected["$exists"]:
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


class FakeBansCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, flt: dict, projection=None, sort=None):
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return docs[0] if docs else None

    def find(self, flt: dict, projection=None, sort=None) -> FakeCursor:
        docs = _sort_docs([doc for doc in self.docs if _matches(doc, flt)], sort)
        return FakeCursor(docs)

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        stored = dict(doc)
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=id(stored))

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        for doc in self.docs:
            if _matches(doc, flt):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def find_one_and_update(
        self,
        flt: dict,
        update: dict,
        return_document=None,
        upsert: bool = False,
    ):
        for doc in self.docs:
            if _matches(doc, flt):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return dict(doc)
        return None

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for doc in self.docs if _matches(doc, flt))


# ──────────────────── Helpers ─────────────────────── #


def _patch(monkeypatch, fake: FakeBansCollection) -> None:
    monkeypatch.setattr(bans_db, "_bans", lambda: fake)


def _ban(
    ban_id: str,
    user_id: int,
    is_active: bool = True,
    timestamp: datetime | None = None,
) -> dict:
    return {
        "ban_id": ban_id,
        "banned_user_id": user_id,
        "is_active": is_active,
        "timestamp": timestamp or datetime(2025, 1, 1, tzinfo=timezone.utc),
    }


# ──────────────────── Reads ─────────────────────── #


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


async def test_get_ban_by_id_returns_matching_doc(monkeypatch) -> None:
    """get_ban returns the document matching the given ban_id."""
    fake = FakeBansCollection([_ban("b001", 10), _ban("b002", 20)])
    _patch(monkeypatch, fake)

    result = await bans_db.get_ban("b002")

    assert result is not None
    assert result["ban_id"] == "b002"


async def test_get_ban_by_id_missing_returns_none(monkeypatch) -> None:
    """get_ban returns None when the ban_id is not present."""
    fake = FakeBansCollection([_ban("b001", 10)])
    _patch(monkeypatch, fake)

    result = await bans_db.get_ban("ghost")

    assert result is None


# ──────────────────── Mutations ─────────────────────── #


async def test_create_ban_inserts_document_with_correct_fields(monkeypatch) -> None:
    """create_ban inserts a new doc and returns it with the expected fields."""
    fake = FakeBansCollection()
    _patch(monkeypatch, fake)
    monkeypatch.setattr(bans_db, "make_ban_id", lambda: "test001")

    doc = await bans_db.create_ban(
        target_id=42,
        reason="spam",
        admin_id=1,
        proof_msg_id=100,
        log_msg_id=200,
    )

    assert doc["ban_id"] == "test001"
    assert doc["banned_user_id"] == 42
    assert doc["reason"] == "spam"
    assert doc["is_active"] is True
    assert doc["update_count"] == 0
    assert len(fake.docs) == 1


async def test_create_ban_uses_provided_ban_id(monkeypatch) -> None:
    """create_ban accepts a pre-generated ban_id and uses it as-is."""
    fake = FakeBansCollection()
    _patch(monkeypatch, fake)

    doc = await bans_db.create_ban(
        target_id=5,
        reason="test",
        admin_id=1,
        proof_msg_id=10,
        log_msg_id=20,
        ban_id="custom001",
    )

    assert doc["ban_id"] == "custom001"


async def test_update_ban_modifies_existing_record(monkeypatch) -> None:
    """update_ban updates reason, admin, proof/log IDs, and increments update_count."""
    initial = {**_ban("up001", 30), "reason": "old", "update_count": 0}
    fake = FakeBansCollection([initial])
    _patch(monkeypatch, fake)

    updated = await bans_db.update_ban(
        ban_id="up001",
        reason="new reason",
        admin_id=9,
        new_proof_id=50,
        new_log_id=60,
        old_proof_id=10,
        old_log_id=20,
    )

    assert updated is not None
    assert updated["reason"] == "new reason"
    assert updated["admin_user_id"] == 9
    assert updated["proof_message_id"] == 50
    assert updated["update_count"] == 1


async def test_update_ban_missing_returns_none(monkeypatch) -> None:
    """update_ban returns None when the ban_id does not exist."""
    fake = FakeBansCollection()
    _patch(monkeypatch, fake)

    result = await bans_db.update_ban(
        ban_id="ghost",
        reason="r",
        admin_id=1,
        new_proof_id=0,
    )

    assert result is None


async def test_deactivate_ban_marks_inactive_and_returns_true(monkeypatch) -> None:
    """deactivate_ban sets is_active=False and returns True when the ban exists."""
    fake = FakeBansCollection([_ban("d001", 50)])
    _patch(monkeypatch, fake)

    result = await bans_db.deactivate_ban("d001")

    assert result is True
    assert fake.docs[0]["is_active"] is False


async def test_deactivate_ban_missing_returns_false(monkeypatch) -> None:
    """deactivate_ban returns False when the ban_id is not found."""
    fake = FakeBansCollection()
    _patch(monkeypatch, fake)

    result = await bans_db.deactivate_ban("ghost")

    assert result is False


async def test_set_log_message_id_updates_field(monkeypatch) -> None:
    """set_log_message_id updates only the log_message_id field of the ban."""
    initial = {**_ban("lg001", 5), "log_message_id": 0}
    fake = FakeBansCollection([initial])
    _patch(monkeypatch, fake)

    await bans_db.set_log_message_id("lg001", 999)

    assert fake.docs[0]["log_message_id"] == 999


# ──────────────────── Statistics ─────────────────────── #


async def test_active_ban_count_counts_only_active(monkeypatch) -> None:
    """active_ban_count counts only is_active=True documents."""
    fake = FakeBansCollection(
        [_ban("a", 1, True), _ban("b", 2, False), _ban("c", 3, True)]
    )
    _patch(monkeypatch, fake)

    count = await bans_db.active_ban_count()

    assert count == 2


async def test_active_ban_user_ids_projection_only(monkeypatch) -> None:
    """active_ban_user_ids returns only the user IDs of active bans."""
    fake = FakeBansCollection(
        [_ban("a", 10, True), _ban("b", 20, False), _ban("c", 30, True)]
    )
    _patch(monkeypatch, fake)

    ids = await bans_db.active_ban_user_ids()

    assert set(ids) == {10, 30}


# ──────────────────── Per-user history ─────────────────────── #


async def test_user_bans_returns_all_bans_for_user(monkeypatch) -> None:
    """user_bans returns active and inactive bans for the specified user."""
    fake = FakeBansCollection(
        [
            _ban("u1", 7, True),
            _ban("u2", 7, False),
            _ban("u3", 8, True),
        ]
    )
    _patch(monkeypatch, fake)

    bans = await bans_db.user_bans(7)

    assert len(bans) == 2
    assert all(b["banned_user_id"] == 7 for b in bans)


async def test_user_ban_count_counts_all_bans(monkeypatch) -> None:
    """user_ban_count includes both active and inactive bans for the user."""
    fake = FakeBansCollection(
        [_ban("x1", 11, True), _ban("x2", 11, False), _ban("x3", 99, True)]
    )
    _patch(monkeypatch, fake)

    count = await bans_db.user_ban_count(11)

    assert count == 2


async def test_user_appeal_count_counts_bans_with_appeal_log(monkeypatch) -> None:
    """user_appeal_count counts bans where appeal_log_msg_id is set."""
    fake = FakeBansCollection(
        [
            {**_ban("ap1", 15), "appeal_log_msg_id": 100},
            {**_ban("ap2", 15), "appeal_log_msg_id": None},
            {**_ban("ap3", 15)},
        ]
    )
    _patch(monkeypatch, fake)

    count = await bans_db.user_appeal_count(15)

    assert count == 1
