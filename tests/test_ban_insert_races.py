# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The ban insert must survive both uniqueness races, verified against PostgreSQL.

Two constraints can reject a ban insert: the unique public reference and
the one-active-ban-per-user rule. The reference collision is retried with
a fresh reference, and that retry can lose the other race. The retry must
take the same path as the first attempt instead of surfacing as a raw
write failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tcbot import cfg
from tcbot.database import bans_db
from tcbot.database import engine as engine_module
from tcbot.database.bans_db import _writes
from tcbot.database.base import moderation_actions, moderation_cases
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community."""
    await reset_community()
    await seed_users(7, 42, 99)
    await seed_chats(cfg.proofs[0])
    yield postgres_db
    await reset_community()


async def _insert_ban(user_id: int, ban_id: str) -> None:
    """Insert one active ban decision straight into the table."""
    case = (
        await engine_module.run_returning(
            moderation_cases.insert()
            .values(
                subject_user_id=user_id,
                title="Raw ban",
                status="open",
                source="manual",
                opened_by_user_id=7,
                requires_evidence=False,
            )
            .returning(moderation_cases.c.id)
        )
    )[0]
    await engine_module.run(
        moderation_actions.insert().values(
            action_type="ban",
            scope_type="community",
            target_user_id=user_id,
            actor_user_id=7,
            reason="spam",
            status="active",
            external_ref=ban_id,
            case_id=case["id"],
            action_origin="automated",
        )
    )


def _fixed_ids(*ids: str) -> Any:
    """Return a generator that hands out the given identifiers in order."""
    remaining = list(ids)

    def _make() -> str:
        return remaining.pop(0) if remaining else "fallbackid01"

    return _make


async def test_the_identifier_retry_keeps_the_canonical_ban(
    ban_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry that loses the active-ban race must reuse the stored record.

    The generated identifier collides, so the insert is retried with a
    fresh one. The retry then finds the target already banned, and the
    helper must hand back the canonical record instead of raising.
    """
    await _insert_ban(42, "canonical01")
    await _insert_ban(99, "collide001")
    monkeypatch.setattr(_writes, "make_ban_id", _fixed_ids("collide001", "fresh00001"))

    record = await bans_db.create_ban(42, "spam", 7, 11, 12)

    assert record.get("ban_id") == "canonical01"
    assert record.get("banned_user_id") == 42


async def test_the_identifier_retry_stores_the_new_ban(
    ban_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry that wins both races must store the new record."""
    await _insert_ban(99, "collide001")
    monkeypatch.setattr(_writes, "make_ban_id", _fixed_ids("collide001", "fresh00001"))

    record = await bans_db.create_ban(42, "spam", 7, 11, 12)

    assert record.get("ban_id") == "fresh00001"
    assert record.get("banned_user_id") == 42
