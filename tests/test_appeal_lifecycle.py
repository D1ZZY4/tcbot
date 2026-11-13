# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""An appeal is a record, not a message.

The appeal against a ban has to be a row of its own: the reviewer
decides on that row, the rejection cooldown reads it, and the audit
trail of who lifted or refused a ban is built from it. The submission
and the review slot therefore land in one transaction, and the decisions
close the row they decided.

The rules the table enforces are checked against the database and not
against a double: only the banned user may appeal, only an active ban
may receive an appeal, and one decision carries one open appeal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import database as db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions, moderation_appeals, moderation_cases
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

# * The public reference of the decision under test. The column accepts
# * ten to thirty-two lowercase alphanumerics.
_BAN_REF: str = "banappeal01"
_TARGET_ID: int = 9
_REVIEWER_ID: int = 1

pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community that holds one active ban."""
    await reset_community()
    await seed_users(_REVIEWER_ID, _TARGET_ID)
    await seed_chats(-1001)
    yield postgres_db
    await reset_community()


async def _store_ban(sess: AsyncSession, *, active: bool = True) -> int:
    """Store one active ban and return its action id.

    A decision is created in its initial status, so a ban that must not
    receive an appeal is created active and revoked afterwards: the
    insert guard refuses a decision that starts in a terminal state.
    """
    case = (
        (
            await sess.execute(
                pg_insert(moderation_cases)
                .values(
                    subject_user_id=_TARGET_ID,
                    title="Appeal under review",
                    status="open",
                    source="manual",
                    opened_by_user_id=_REVIEWER_ID,
                    requires_evidence=False,
                )
                .returning(moderation_cases.c.id)
            )
        )
        .mappings()
        .first()
    )
    assert case is not None
    action = (
        (
            await sess.execute(
                pg_insert(moderation_actions)
                .values(
                    action_type="ban",
                    scope_type="community",
                    target_user_id=_TARGET_ID,
                    actor_user_id=_REVIEWER_ID,
                    reason="spam",
                    status="active",
                    external_ref=_BAN_REF,
                    case_id=case["id"],
                    metadata={},
                    # * The automated origin needs no archived proof, so
                    # * the test can file the decision without one.
                    action_origin="automated",
                )
                .returning(moderation_actions.c.id)
            )
        )
        .mappings()
        .first()
    )
    assert action is not None
    if not active:
        await sess.execute(
            moderation_actions.update()
            .where(moderation_actions.c.id == action["id"])
            .values(status="revoked")
        )
    return int(action["id"])


async def _appeals() -> list[dict[str, Any]]:
    """Return every appeal of the decision under test."""
    return await engine_module.fetch_all(
        moderation_appeals.select().order_by(moderation_appeals.c.id)
    )


async def _seed_ban(active: bool = True) -> int:  # noqa: FBT001, FBT002
    """Store the decision under test in its own transaction."""

    async def _work(sess: AsyncSession) -> int:
        return await _store_ban(sess, active=active)

    return await engine_module.run_transaction(_work)


async def test_the_submission_records_the_appeal(ban_db: str) -> None:
    """A submitted appeal becomes a row of its own."""
    await _seed_ban()

    claimed = await db.bans_db.submit_appeal(
        _BAN_REF, _TARGET_ID, "please reconsider", 77
    )

    assert claimed is True
    rows = await _appeals()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["appellant_user_id"] == _TARGET_ID
    assert rows[0]["appeal_text"] == "please reconsider"
    assert rows[0]["reviewed_by_user_id"] is None


async def test_the_decision_carries_the_claimed_slot(ban_db: str) -> None:
    """The submission claims the review slot of the decision."""
    await _seed_ban()

    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    ban = await db.bans_db.get_ban(_BAN_REF)
    assert ban is not None
    assert ban.get("review_message_id") == 77


async def test_a_second_submission_is_refused(ban_db: str) -> None:
    """A decision that carries an open appeal does not take a second one."""
    await _seed_ban()

    first = await db.bans_db.submit_appeal(
        _BAN_REF, _TARGET_ID, "please reconsider", 77
    )
    second = await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "again please", 78)

    assert first is True
    assert second is False
    rows = await _appeals()
    assert len(rows) == 1
    assert rows[0]["appeal_text"] == "please reconsider"


async def test_the_acceptance_closes_the_appeal(ban_db: str) -> None:
    """An accepted appeal names the reviewer and the moment of the decision."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    accepted = await db.bans_db.accept_appeal(_BAN_REF, _REVIEWER_ID, "Admin")

    assert accepted is True
    rows = await _appeals()
    assert rows[0]["status"] == "accepted"
    assert rows[0]["reviewed_by_user_id"] == _REVIEWER_ID
    assert rows[0]["resolved_at"] is not None


async def test_the_acceptance_shows_up_on_the_decision(ban_db: str) -> None:
    """The decision carries the outcome of the appeal it received."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    await db.bans_db.accept_appeal(_BAN_REF, _REVIEWER_ID, "Admin")

    ban = await db.bans_db.get_ban(_BAN_REF)
    assert ban is not None
    assert ban.get("rejected_by_id") == _REVIEWER_ID
    assert ban.get("rejected_at") is not None


async def test_the_rejection_closes_the_appeal(ban_db: str) -> None:
    """A rejected appeal names the reviewer."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    await db.bans_db.set_rejected_by(_BAN_REF, _REVIEWER_ID, "Admin")

    rows = await _appeals()
    assert rows[0]["status"] == "rejected"
    assert rows[0]["reviewed_by_user_id"] == _REVIEWER_ID
    assert rows[0]["resolved_at"] is not None


async def test_a_rejected_decision_takes_a_new_appeal(ban_db: str) -> None:
    """A closed appeal releases the decision for a later appeal."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)
    await db.bans_db.set_rejected_by(_BAN_REF, _REVIEWER_ID, "Admin")
    await db.bans_db.clear_review(_BAN_REF)

    claimed = await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "again please", 78)

    assert claimed is True
    rows = await _appeals()
    assert len(rows) == 2
    assert rows[0]["status"] == "rejected"
    assert rows[1]["status"] == "pending"


async def test_the_stale_release_withdraws_the_appeal(ban_db: str) -> None:
    """A stale card is released together with the appeal it belongs to."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    withdrawn = await db.bans_db.release_stale_review(_BAN_REF)

    assert withdrawn is True
    rows = await _appeals()
    assert rows[0]["status"] == "withdrawn"
    ban = await db.bans_db.get_ban(_BAN_REF)
    assert ban is not None
    assert ban.get("review_message_id") is None


async def test_the_stale_release_lets_a_new_appeal_in(ban_db: str) -> None:
    """A withdrawn appeal does not occupy the decision any more."""
    await _seed_ban()
    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)
    await db.bans_db.release_stale_review(_BAN_REF)

    claimed = await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "again please", 78)

    assert claimed is True
    rows = await _appeals()
    assert len(rows) == 2
    assert rows[1]["status"] == "pending"


async def test_only_the_banned_user_may_appeal(ban_db: str) -> None:
    """The database refuses an appeal from somebody else."""
    await _seed_ban()

    with pytest.raises(Exception):  # noqa: B017
        await db.bans_db.submit_appeal(_BAN_REF, 42, "not my ban", 77)

    assert await _appeals() == []


async def test_a_refused_submission_leaves_the_slot_free(ban_db: str) -> None:
    """A refused submission does not claim the review slot of the decision.

    The claim and the appeal row are one unit of work: when the insert
    fails, the claim has to fail with it. A claim that survived the
    failure would block every later appeal for the decision, because the
    slot would stay occupied by an appeal row that does not exist.
    """
    await _seed_ban()

    with pytest.raises(Exception):  # noqa: B017
        await db.bans_db.submit_appeal(_BAN_REF, 42, "not my ban", 77)

    ban = await db.bans_db.get_ban(_BAN_REF)
    assert ban is not None
    assert ban.get("review_message_id") is None


async def test_the_banned_user_may_appeal_after_a_refused_submission(
    ban_db: str,
) -> None:
    """The refused submission left nothing behind that blocks a later appeal."""
    await _seed_ban()

    with pytest.raises(Exception):  # noqa: B017
        await db.bans_db.submit_appeal(_BAN_REF, 42, "not my ban", 77)

    claimed = await db.bans_db.submit_appeal(
        _BAN_REF, _TARGET_ID, "please reconsider", 78
    )

    assert claimed is True
    rows = await _appeals()
    assert len(rows) == 1
    assert rows[0]["appellant_user_id"] == _TARGET_ID


async def test_only_an_active_ban_may_receive_an_appeal(ban_db: str) -> None:
    """The database refuses an appeal against a decision that was lifted."""
    await _seed_ban(active=False)

    claimed = await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "too late", 77)

    assert claimed is False
    assert await _appeals() == []


async def test_the_appeal_count_follows_the_records(ban_db: str) -> None:
    """The appeal count of a user counts the rows that exist."""
    await _seed_ban()

    assert await db.bans_db.user_appeal_count(_TARGET_ID) == 0

    await db.bans_db.submit_appeal(_BAN_REF, _TARGET_ID, "please reconsider", 77)

    assert await db.bans_db.user_appeal_count(_TARGET_ID) == 1
