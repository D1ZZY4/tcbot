# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Offline tests for tcbot.database.users_roles - core federation authorization logic.

Covers role-rank comparison, owner/admin/role CRUD, and effective-role resolution
including the in-process role cache. MongoDB is replaced with in-memory fakes so the
suite stays offline and deterministic.
"""

from __future__ import annotations

import pytest

from tcbot.database import users_roles
from tcbot.database.cache import effective_role_cache, owner_id_cache

# ───────────────────────────── Fakes ────────────────────────────── #


def _match_value(value: object, expected: object) -> bool:
    if isinstance(expected, dict):
        if "$ne" in expected:
            return value != expected["$ne"]
        return False
    return value == expected


def _matches(doc: dict, flt: dict) -> bool:
    return all(_match_value(doc.get(key), expected) for key, expected in flt.items())


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return [dict(doc) for doc in self._docs]


class FakeCollection:
    """Minimal in-memory stand-in for an AsyncIOMotorCollection."""

    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = [dict(doc) for doc in docs or []]

    async def find_one(self, flt: dict, projection: dict | None = None):
        for doc in self.docs:
            if _matches(doc, flt):
                return dict(doc)
        return None

    def find(
        self, flt: dict | None = None, projection: dict | None = None
    ) -> FakeCursor:
        flt = flt or {}
        return FakeCursor([doc for doc in self.docs if _matches(doc, flt)])

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for doc in self.docs if _matches(doc, flt))

    async def insert_one(self, doc: dict):
        self.docs.append(dict(doc))
        return _Result(inserted_id=doc.get("user_id"))

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        for doc in self.docs:
            if _matches(doc, flt):
                if "$set" in update:
                    doc.update(update["$set"])
                return _Result(matched_count=1, modified_count=1)
        if upsert:
            new = {key: val for key, val in flt.items() if not isinstance(val, dict)}
            if "$setOnInsert" in update:
                new.update(update["$setOnInsert"])
            if "$set" in update:
                new.update(update["$set"])
            self.docs.append(new)
            return _Result(
                matched_count=0, modified_count=0, upserted_id=new.get("user_id")
            )
        return _Result(matched_count=0, modified_count=0)

    async def delete_one(self, flt: dict):
        for idx, doc in enumerate(self.docs):
            if _matches(doc, flt):
                del self.docs[idx]
                return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    async def delete_many(self, flt: dict):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, flt)]
        return _Result(deleted_count=before - len(self.docs))


class _Result:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class FakeDB:
    """Dispatches ``col(name)`` to the matching in-memory collection."""

    def __init__(
        self,
        owners: list[dict] | None = None,
        admins: list[dict] | None = None,
        roles: list[dict] | None = None,
    ) -> None:
        self.collections: dict[str, FakeCollection] = {
            "tc_owners": FakeCollection(owners),
            "tc_admins": FakeCollection(admins),
            "tc_roles": FakeCollection(roles),
        }

    def __call__(self, name: str) -> FakeCollection:
        return self.collections[name]


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Reset the shared role caches so tests never leak state into each other."""
    owner_id_cache.clear()
    effective_role_cache.clear()


def _install(monkeypatch, db: FakeDB) -> None:
    monkeypatch.setattr(users_roles, "col", db)


# ──────────────────────────── role_rank ─────────────────────────── #


def test_role_rank_orders_hierarchy() -> None:
    assert users_roles.role_rank("founder") == 4
    assert users_roles.role_rank("admin") == 3
    assert users_roles.role_rank("developer") == 2
    assert users_roles.role_rank("tester") == 1


def test_role_rank_unknown_and_none_are_zero() -> None:
    assert users_roles.role_rank(None) == 0
    assert users_roles.role_rank("") == 0
    assert users_roles.role_rank("nonsense") == 0


# ───────────────────────── Owner / admin reads ──────────────────── #


async def test_is_owner_true_and_false(monkeypatch) -> None:
    _install(monkeypatch, FakeDB(owners=[{"user_id": 10}]))
    assert await users_roles.is_owner(10) is True
    assert await users_roles.is_owner(11) is False


async def test_is_admin_true_and_false(monkeypatch) -> None:
    _install(monkeypatch, FakeDB(admins=[{"user_id": 20}]))
    assert await users_roles.is_admin(20) is True
    assert await users_roles.is_admin(21) is False


async def test_is_staff_covers_owner_and_admin(monkeypatch) -> None:
    _install(monkeypatch, FakeDB(owners=[{"user_id": 1}], admins=[{"user_id": 2}]))
    assert await users_roles.is_staff(1) is True
    assert await users_roles.is_staff(2) is True
    assert await users_roles.is_staff(3) is False


# ───────────────────── Effective-role resolution ────────────────── #


async def test_get_effective_role_resolution_order(monkeypatch) -> None:
    _install(
        monkeypatch,
        FakeDB(
            owners=[{"user_id": 1}],
            admins=[{"user_id": 2}],
            roles=[{"user_id": 3, "role": "developer"}],
        ),
    )
    assert await users_roles.get_effective_role(1) == "founder"
    assert await users_roles.get_effective_role(2) == "admin"
    assert await users_roles.get_effective_role(3) == "developer"
    assert await users_roles.get_effective_role(99) is None


async def test_can_act_on_compares_ranks(monkeypatch) -> None:
    _install(
        monkeypatch,
        FakeDB(
            owners=[{"user_id": 1}],
            admins=[{"user_id": 2}],
            roles=[{"user_id": 3, "role": "tester"}],
        ),
    )
    assert await users_roles.can_act_on(1, 2) is True  # founder over admin
    assert await users_roles.can_act_on(2, 3) is True  # admin over tester
    assert await users_roles.can_act_on(3, 2) is False  # tester under admin
    assert await users_roles.can_act_on(2, 2) is False  # equal rank cannot act


# ──────────────────────── Owner seeding / swap ──────────────────── #


async def test_ensure_initial_owner_seeds_empty_collection(monkeypatch) -> None:
    db = FakeDB()
    _install(monkeypatch, db)
    await users_roles.ensure_initial_owner(500)
    assert await users_roles.is_owner(500) is True


async def test_ensure_initial_owner_is_noop_when_present(monkeypatch) -> None:
    db = FakeDB(owners=[{"user_id": 7}])
    _install(monkeypatch, db)
    await users_roles.ensure_initial_owner(500)
    assert await users_roles.is_owner(7) is True
    assert await users_roles.is_owner(500) is False


async def test_set_owner_replaces_previous_owner(monkeypatch) -> None:
    db = FakeDB(owners=[{"user_id": 7}])
    _install(monkeypatch, db)
    await users_roles.set_owner(8)
    assert await users_roles.is_owner(8) is True
    assert await users_roles.is_owner(7) is False


# ─────────────────────────── Admin CRUD ─────────────────────────── #


async def test_add_admin_then_remove_admin(monkeypatch) -> None:
    db = FakeDB()
    _install(monkeypatch, db)

    await users_roles.add_admin(30, promoted_by=1)
    assert await users_roles.is_admin(30) is True
    assert await users_roles.admin_count() == 1

    removed = await users_roles.remove_admin(30)
    assert removed is True
    assert await users_roles.is_admin(30) is False


async def test_remove_admin_returns_false_when_absent(monkeypatch) -> None:
    _install(monkeypatch, FakeDB())
    assert await users_roles.remove_admin(999) is False


# ─────────────────────── Custom role CRUD ───────────────────────── #


async def test_set_role_then_get_role(monkeypatch) -> None:
    db = FakeDB()
    _install(monkeypatch, db)

    await users_roles.set_role(40, "tester", assigned_by=1)
    assert await users_roles.get_role(40) == "tester"

    removed = await users_roles.remove_role(40)
    assert removed is True
    assert await users_roles.get_role(40) is None


# ───────────────── Cache invalidation on role writes ────────────── #


async def test_effective_role_cache_refreshes_after_promotion(monkeypatch) -> None:
    db = FakeDB()
    _install(monkeypatch, db)

    # First lookup caches the "no role" result.
    assert await users_roles.get_effective_role(50) is None

    # add_admin must invalidate the cache so the next read reflects the new rank.
    await users_roles.add_admin(50, promoted_by=1)
    assert await users_roles.get_effective_role(50) == "admin"
