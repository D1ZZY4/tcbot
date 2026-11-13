# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The review slot of a decision is claimed atomically in the database.

Two moderators can file an appeal for the same ban, and two reviewers can
tap the same review card. The slot that belongs to the decision decides
which of them wins, so the claim has to be a single conditional update:
a read followed by a write lets the second writer overwrite the first.

The metadata of the decision is a JSONB object that other writers also
use, so a slot write has to merge into it. Replacing the object would
drop the keys another writer added in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import database as db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_cases
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

# * The public reference of the decision under test. The column accepts
# * ten to thirty-two lowercase alphanumerics.
_BAN_REF: str = "banreview02"

pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community that holds one decision."""
    await reset_community()
    await seed_users(1, 9)
    await seed_chats(-1001)
    yield postgres_db
    await reset_community()


async def _store_ban(
    sess: AsyncSession,
    *,
    ban_id: str = _BAN_REF,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Store one decision with the given metadata."""
    case = (
        (
            await sess.execute(
                pg_insert(moderation_cases)
                .values(
                    subject_user_id=9,
                    title="Appeal under review",
                    status="open",
                    source="manual",
                    opened_by_user_id=1,
                    requires_evidence=False,
                )
                .returning(moderation_cases.c.id)
            )
        )
        .mappings()
        .first()
    )
    assert case is not None
    await sess.execute(
        pg_insert(moderation_actions).values(
            action_type="ban",
            scope_type="community",
            target_user_id=9,
            actor_user_id=1,
            reason="spam",
            status="active",
            external_ref=ban_id,
            case_id=case["id"],
            metadata=metadata or {},
            # * The automated origin needs no archived proof, so the test
            # * can file the decision without one.
            action_origin="automated",
        )
    )


async def _metadata(ban_id: str = _BAN_REF) -> dict[str, Any]:
    """Return the metadata stored with the decision."""
    row = await engine_module.fetch_one(
        moderation_actions.select().where(moderation_actions.c.external_ref == ban_id)
    )
    assert row is not None
    return dict(row["metadata"] or {})


async def test_the_slot_is_claimed_only_once(ban_db: str) -> None:
    """Two concurrent appeals cannot both claim the review slot."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess)

    await engine_module.run_transaction(_work)

    first = await db.bans_db.set_review_if_absent(_BAN_REF, 77)
    second = await db.bans_db.set_review_if_absent(_BAN_REF, 78)

    assert first is True
    assert second is False
    metadata = await _metadata()
    assert metadata["review_message_id"] == 77


async def test_the_slot_claim_keeps_the_other_metadata(ban_db: str) -> None:
    """Claiming the slot merges into the metadata instead of replacing it.

    The duration and the update counter live in the same object, and a
    replace would drop them.
    """

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess, metadata={"duration_str": "7d", "update_count": 2})

    await engine_module.run_transaction(_work)

    claimed = await db.bans_db.set_review_if_absent(_BAN_REF, 77)

    assert claimed is True
    metadata = await _metadata()
    assert metadata["duration_str"] == "7d"
    assert metadata["update_count"] == 2
    assert metadata["review_message_id"] == 77


async def test_the_slot_is_cleared_without_touching_the_rest(ban_db: str) -> None:
    """Clearing the slot removes the review keys and keeps the others."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess, metadata={"duration_str": "7d"})

    await engine_module.run_transaction(_work)
    assert await db.bans_db.set_review_if_absent(_BAN_REF, 77) is True

    await db.bans_db.clear_review(_BAN_REF)

    metadata = await _metadata()
    assert "review_message_id" not in metadata
    assert "review_timestamp" not in metadata
    assert metadata["duration_str"] == "7d"


async def test_the_decision_claim_only_matches_its_own_card(ban_db: str) -> None:
    """A claim for another review message does not consume the slot."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess)

    await engine_module.run_transaction(_work)
    assert await db.bans_db.set_review_if_absent(_BAN_REF, 77) is True

    other = await db.bans_db.claim_appeal_decision(_BAN_REF, 78)
    own = await db.bans_db.claim_appeal_decision(_BAN_REF, 77)

    assert other is False
    assert own is True
    metadata = await _metadata()
    assert "review_message_id" not in metadata


async def test_the_decision_claim_needs_an_active_ban(ban_db: str) -> None:
    """A claim on a revoked decision changes nothing."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess)
        await sess.execute(
            moderation_actions.update()
            .where(moderation_actions.c.external_ref == _BAN_REF)
            .values(status="revoked")
        )

    await engine_module.run_transaction(_work)
    assert await db.bans_db.set_review_if_absent(_BAN_REF, 77) is True

    claimed = await db.bans_db.claim_appeal_decision(_BAN_REF, 77)

    assert claimed is False
    metadata = await _metadata()
    assert metadata["review_message_id"] == 77


async def test_a_missing_decision_claims_nothing(ban_db: str) -> None:
    """A reference that names no decision cannot claim a slot."""
    assert await db.bans_db.set_review_if_absent("nosuchban01", 77) is False
    assert await db.bans_db.claim_appeal_decision("nosuchban01", 77) is False
