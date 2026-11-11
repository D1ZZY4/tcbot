# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Critical authorization, expiry, and failure-mode contracts of the moderation core."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.database import bans_db, mutes_db
from tcbot.modules.helper.decorators import checks, ratelimit

# ────────────────────────────── Role rules ────────────────────────────── #


def test_can_demote_admin_requires_the_founder() -> None:
    """Only the Founder may remove an Admin role."""
    assert checks.can_demote_admin("founder", "admin") is True
    assert checks.can_demote_admin("admin", "admin") is False
    assert checks.can_demote_admin("developer", "admin") is False
    # * Every other target follows the normal rank rule.
    assert checks.can_demote_admin("admin", "developer") is True
    assert checks.can_demote_admin("admin", "tester") is True
    assert checks.can_demote_admin("admin", None) is True


def test_role_rank_orders_the_federation_hierarchy() -> None:
    """The rank table is the single source of truth for comparisons."""
    ranks = [
        db.users_roles.role_rank(role)
        for role in ("founder", "admin", "developer", "tester", None, "bogus")
    ]
    assert ranks == sorted(ranks, reverse=True)
    assert db.users_roles.role_rank(None) == 0
    assert db.users_roles.role_rank("bogus") == 0


# ───────────────────────── Rate-limit exemption ───────────────────────── #


def test_the_throttle_tiers_keep_their_budgets() -> None:
    """The shared throttle tiers must keep the budgets they replaced.

    Every command module used to declare its own pair of constants. The
    shared table replaced those, so the numbers are pinned here: a change
    to a tier is a deliberate change to how hard the bot throttles a user.
    """
    expected = {
        "THROTTLE_READ": (8, 30.0),
        "THROTTLE_CALLBACK": (15, 30.0),
        "THROTTLE_CALLBACK_DEEP": (20, 30.0),
        "THROTTLE_STAFF": (10, 30.0),
        "THROTTLE_MODERATION": (5, 60.0),
        "THROTTLE_FEDERATION": (3, 60.0),
        "THROTTLE_BULK": (3, 300.0),
        "THROTTLE_CRITICAL": (1, 300.0),
        "THROTTLE_SWEEP": (2, 300.0),
    }
    actual = {
        name: (getattr(ratelimit, name).limit, getattr(ratelimit, name).period)
        for name in expected
    }
    assert actual == expected


def test_founder_bypasses_the_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Founder is exempt from the per-user quotas."""

    async def _owner(*args: Any, **kwargs: Any) -> int:
        _ = (args, kwargs)
        return 1

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    assert asyncio.run(ratelimit._is_exempt(1)) is True
    assert asyncio.run(ratelimit._is_exempt(2)) is False


def test_rate_limit_exemption_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lookup outage must not exempt anyone."""

    async def _boom(*args: Any, **kwargs: Any) -> int:
        _ = (args, kwargs)
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_owner_id", _boom)
    assert asyncio.run(ratelimit._is_exempt(1)) is False


def test_rate_limit_exemption_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must not be read as "not exempt"."""

    async def _cancelled(*args: Any, **kwargs: Any) -> int:
        _ = (args, kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_owner_id", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ratelimit._is_exempt(1))


def test_throttle_tier_resolves_the_flood_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder, staff, and everyone else get their own bucket."""
    roles = {1: "founder", 2: "tester", 3: None}

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        _ = fresh
        return roles.get(user_id)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assert asyncio.run(ratelimit._throttle_tier(1)) == "exempt"
    assert asyncio.run(ratelimit._throttle_tier(2)) == "staff"
    assert asyncio.run(ratelimit._throttle_tier(3)) == "regular"


def test_throttle_tier_fails_closed_to_the_strict_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup outage must not loosen throttling."""

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        _ = (user_id, fresh)
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    assert asyncio.run(ratelimit._throttle_tier(1)) == "regular"


# ─────────────────────────── Mute expiry rules ────────────────────────── #


def test_mute_expiry_clause_keeps_permanent_mutes() -> None:
    """A permanent mute never expires; a timed one expires with its window."""
    now = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    clause = mutes_db._not_expired_clause(now)
    branches: list[dict[str, Any]] = clause["$or"]  # type: ignore[assignment]
    assert {"until_date": None} in branches
    assert {"until_date": {"$gt": now}} in branches


def test_active_mute_reads_exclude_expired_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired timed mute is not returned as active."""
    captured: dict[str, Any] = {}

    class _Collection:
        def find_one(self, filt: dict[str, Any], *args: Any) -> None:
            _ = args
            captured["filter"] = filt
            return

    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: _Collection())

    assert asyncio.run(mutes_db.get_active_mute(42)) is None
    filt: dict[str, Any] = captured["filter"]
    assert filt["user_id"] == 42
    assert "$or" in filt


def test_active_mute_documents_exclude_expired_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replay list only carries still-valid mutes."""
    captured: dict[str, Any] = {}

    class _Collection:
        def find(self, filt: dict[str, Any], *args: Any) -> list[dict[str, Any]]:
            _ = args
            captured["filter"] = filt
            return []

    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: _Collection())

    assert asyncio.run(mutes_db.active_mute_docs()) == []
    assert "$or" in captured["filter"]


def test_permanent_mute_row_is_never_ttl_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permanent mute stores a null expiry, so the TTL index keeps it."""
    captured: dict[str, Any] = {}

    class _Collection:
        def update_one(
            self, filt: dict[str, Any], update: dict[str, Any], **kw: Any
        ) -> None:
            _ = (filt, kw)
            captured["until"] = update["$set"]["until_date"]

    monkeypatch.setattr(mutes_db, "_active_mutes", lambda: _Collection())

    asyncio.run(mutes_db.set_active_mute(42))
    assert captured["until"] is None

    asyncio.run(
        mutes_db.set_active_mute(42, until=datetime.now(UTC) + timedelta(hours=1))
    )
    assert captured["until"] is not None


# ─────────────────────────── Ban DB atomicity ─────────────────────────── #


def test_review_slot_claim_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first appeal submission may claim the review slot."""
    results = iter([1, 0])

    class _Collection:
        def update_one(self, filt: dict[str, Any], update: dict[str, Any]) -> Any:
            _ = (filt, update)
            return SimpleNamespace(modified_count=next(results))

    monkeypatch.setattr(bans_db, "_bans", lambda: _Collection())

    assert asyncio.run(bans_db.set_review_if_absent("b1", 100)) is True
    assert asyncio.run(bans_db.set_review_if_absent("b1", 200)) is False


def test_appeal_decision_claim_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first approve/reject tap may claim the decision."""
    results = iter([1, 0])

    class _Collection:
        def update_one(self, filt: dict[str, Any], update: dict[str, Any]) -> Any:
            _ = (filt, update)
            return SimpleNamespace(modified_count=next(results))

    monkeypatch.setattr(bans_db, "_bans", lambda: _Collection())

    assert asyncio.run(bans_db.claim_appeal_decision("b1", 100)) is True
    assert asyncio.run(bans_db.claim_appeal_decision("b1", 100)) is False


def test_duplicate_active_bans_are_deactivated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the canonical record survives a duplicate cleanup."""
    captured: dict[str, Any] = {}

    class _Collection:
        def update_many(self, filt: dict[str, Any], update: dict[str, Any]) -> Any:
            captured["filter"] = filt
            captured["update"] = update
            return SimpleNamespace(modified_count=1)

    monkeypatch.setattr(bans_db, "_bans", lambda: _Collection())

    count = asyncio.run(bans_db.deactivate_extra_active_bans(42, "keep"))
    assert count == 1
    assert captured["filter"]["ban_id"] == {"$ne": "keep"}
    assert captured["update"] == {"$set": {"is_active": False}}


# ────────────────────── Cross-group isolation ─────────────────────────── #


def test_primary_groups_merge_does_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A group already in the list is not added twice."""
    groups = [{"chat_id": -1001, "title": "A"}]
    merged = db.groups_db.with_primary_groups(
        groups,  # type: ignore[arg-type]
        (-1002,),
        -1001,
    )
    ids = [g["chat_id"] for g in merged]
    assert ids.count(-1001) == 1
    assert -1002 in ids


def test_primary_groups_merge_skips_unset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset primary id is skipped instead of creating a bogus group."""
    merged = db.groups_db.with_primary_groups([], (0,), 0)
    assert merged == []
