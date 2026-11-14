# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A review slot must survive a tap that reaches no decision.

The decision claim consumes the review slot so only one reviewer acts on
it. A tap that is refused (the approver does not outrank the target) or
that fails (the database is down) reaches no decision, so it must hand
the slot back. Otherwise the review card dies with the appeal undecided
and the banned user can appeal again at once.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from tcbot import database as db
from tcbot.database import engine as engine_module
from tcbot.database.base import moderation_actions
from tcbot.modules.helper.pipelines import appeal_review_flow
from tests.postgres_support import (
    reset_community,
    seed_action,
    seed_appeal,
    seed_case,
    seed_chats,
    seed_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

# * The public reference of the decision under test. The column accepts
# * ten to thirty-two lowercase alphanumerics, so the reference has to
# * be at least ten characters long.
_BAN_REF: str = "banreview01"


class _FakeQuery:
    """A callback query that records the answers."""

    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []

    async def answer(
        self, text: str = "", *, show_alert: bool = False, **kwargs: Any
    ) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        return None


class _FakeBot:
    """A bot that accepts every call the review path makes."""

    async def send_message(self, *a: Any, **k: Any) -> Any:
        return type("M", (), {"message_id": 1})()

    async def unban_chat_member(self, *a: Any, **k: Any) -> None:
        return None


def _fake_update(query: _FakeQuery, user_id: int) -> Any:
    """Return an update carrying the callback query and the reviewer."""
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id, "first_name": "Admin"})(),
        },
    )()


def _ban(target_role: str = "admin") -> dict[str, Any]:
    """Return an active ban with a pending review card.

    The reviewer is the moderator that issued the ban, so the exclusive
    review window does not lock them out.
    """
    return {
        "ban_id": _BAN_REF,
        "is_active": True,
        "review_message_id": 1,
        "review_timestamp": datetime.now(UTC),
        "actor_user_id": 1,
        "target_user_id": 9,
        "rejected_at": None,
        "appeal_link": "",
        "appeal_submitted_at": None,
        "appeal_log_msg_id": 0,
        "_target_role": target_role,
    }


def _wire(monkeypatch: pytest.MonkeyPatch, *, claimed: bool = True) -> dict[str, Any]:
    """Wire the review path with recording doubles; returns the recorders."""
    record: dict[str, Any] = {"restored": [], "deactivated": []}
    ban = _ban()

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        # * The reviewer is an admin; the target holds an admin role too,
        # * so the approve path refuses the tap on the rank rule.
        return "admin"

    async def _get_ban(ban_id: str) -> dict[str, Any]:
        return ban

    async def _claim(ban_id: str, review_msg_id: int) -> bool:
        return claimed

    async def _restore(
        ban_id: str, review_msg_id: int, review_timestamp: Any = None
    ) -> bool:
        record["restored"].append((ban_id, review_msg_id))
        return True

    async def _fname(user_id: int, fallback: str = "") -> str:
        return fallback

    async def _groups() -> list[Any]:
        return []

    async def _deactivate(target_id: int) -> int:
        record["deactivated"].append(target_id)
        return 1

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _locale_user(user_id: int) -> str:
        return "en-US"

    async def _clear(ban_id: str) -> None:
        return None

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.bans_db, "get_ban", _get_ban)
    monkeypatch.setattr(db.bans_db, "claim_appeal_decision", _claim)
    monkeypatch.setattr(db.bans_db, "restore_review", _restore)
    monkeypatch.setattr(db.bans_db, "deactivate_all_active_bans", _deactivate)
    monkeypatch.setattr(db.bans_db, "clear_review", _clear)
    monkeypatch.setattr(db.users_cache, "get_first_name", _fname)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(appeal_review_flow, "locale_for_update", _locale)
    monkeypatch.setattr(appeal_review_flow, "locale_for_user", _locale_user)
    return record


def _run_decision(query: _FakeQuery, reviewer_id: int = 1) -> None:
    """Run the review callback for the given reviewer."""
    ctx = type("Ctx", (), {"bot": _FakeBot()})()
    asyncio.run(
        appeal_review_flow.AppealReviewMixin().on_decision(
            _fake_update(query, reviewer_id),  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
        )
    )


def test_a_refused_tap_gives_the_review_slot_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reviewer who does not outrank the target must not burn the slot.

    The refusal is about the reviewer, not about the appeal, so the card
    has to stay live for a reviewer who does hold the rank.
    """
    record = _wire(monkeypatch)

    query = _FakeQuery(f"appeal_approve_{_BAN_REF}")
    _run_decision(query)

    assert record["deactivated"] == []
    assert record["restored"] == [(_BAN_REF, 1)]


def test_a_lost_claim_does_not_restore_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer who lost the race must not put the slot back."""
    record = _wire(monkeypatch, claimed=False)

    query = _FakeQuery(f"appeal_approve_{_BAN_REF}")
    _run_decision(query)

    assert record["restored"] == []


# ─────────────────────── The restore contract ────────────────────── #
# * The restore is the safety argument of the whole feature, so its
# * filters are checked against the database and not against a double.


@pytest.fixture
async def ban_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community."""
    await reset_community()
    await seed_users(1, 9)
    await seed_chats(-1001)
    yield postgres_db
    await reset_community()


async def _store_ban(
    sess: AsyncSession,
    *,
    ban_id: str = _BAN_REF,
    active: bool = True,
    rejected: bool = False,
    review_message_id: int | None = None,
) -> None:
    """Store one decision with the review state under test."""
    case_id = await seed_case(9, opened_by_user_id=1, title="Appeal under review")
    metadata: dict[str, Any] = {}
    if review_message_id is not None:
        metadata["review_message_id"] = review_message_id
    action_id = await seed_action(
        "ban",
        9,
        actor_user_id=1,
        reason="spam",
        external_ref=ban_id,
        case_id=case_id,
        metadata=metadata,
        # * The automated origin needs no archived proof, so the test can
        # * file the decision without one.
        action_origin="automated",
        status="active" if active else "revoked",
    )
    if rejected:
        await seed_appeal(
            action_id,
            9,
            status="rejected",
            reviewed_by_user_id=1,
            decision_note="Admin",
        )


async def _review_message_id(ban_id: str = _BAN_REF) -> Any:
    """Return the review message id stored with the decision."""
    row = await engine_module.fetch_one(
        moderation_actions.select().where(moderation_actions.c.external_ref == ban_id)
    )
    assert row is not None
    metadata = row["metadata"] or {}
    return metadata.get("review_message_id")


async def test_the_restore_fills_an_empty_slot(ban_db: str) -> None:
    """An active, unrejected ban gets its review slot back."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess)

    await engine_module.run_transaction(_work)

    restored = await db.bans_db.restore_review(_BAN_REF, 77, datetime.now(UTC))

    assert restored is True
    assert await _review_message_id() == 77


async def test_the_restore_skips_a_decided_ban(ban_db: str) -> None:
    """A ban that was already approved keeps its empty slot.

    The approval deactivated the ban, so the appeal is decided. A restore
    would bring the review card back and let a second reviewer act on it.
    """

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess, active=False)

    await engine_module.run_transaction(_work)

    restored = await db.bans_db.restore_review(_BAN_REF, 77, datetime.now(UTC))

    assert restored is False
    assert await _review_message_id() is None


async def test_the_restore_skips_a_rejected_ban(ban_db: str) -> None:
    """A rejected appeal keeps its empty slot."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess, rejected=True)

    await engine_module.run_transaction(_work)

    restored = await db.bans_db.restore_review(_BAN_REF, 77, datetime.now(UTC))

    assert restored is False
    assert await _review_message_id() is None


async def test_the_restore_never_overwrites_a_filled_slot(ban_db: str) -> None:
    """A slot that a new appeal already claimed is left alone."""

    async def _work(sess: AsyncSession) -> None:
        await _store_ban(sess, review_message_id=99)

    await engine_module.run_transaction(_work)

    restored = await db.bans_db.restore_review(_BAN_REF, 77, datetime.now(UTC))

    assert restored is False
    assert await _review_message_id() == 99
