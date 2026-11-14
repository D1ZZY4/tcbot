# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review hardening: self-review blocked; staff approve demotes first."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import appeal_review_flow, demote_flow
from tcbot.utils.i18n import t


class _FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []
        self.edits: list[str] = []

    async def answer(
        self, text: str = "", *, show_alert: bool = False, **kwargs: Any
    ) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)


class _FakeBot:
    async def send_message(self, *a: Any, **k: Any) -> Any:
        return type("M", (), {"message_id": 1})()

    async def unban_chat_member(self, *a: Any, **k: Any) -> None:
        return None

    async def edit_message_text(self, *a: Any, **k: Any) -> None:
        return None


def _fake_update(query: _FakeQuery, user_id: int) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id})(),
        },
    )()


def test_self_review_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    ban: dict[str, Any] = {
        "ban_id": "abc",
        "is_active": True,
        "review_message_id": 1,
        "review_timestamp": datetime.now(UTC),
        "actor_user_id": 7,
        "target_user_id": 7,
        "rejected_at": None,
    }

    async def _ban(ban_id: str) -> dict[str, Any]:
        return ban

    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.bans_db, "get_ban", _ban)
    monkeypatch.setattr(appeal_review_flow, "locale_for_update", _locale)
    query = _FakeQuery("appeal_approve_abc")
    asyncio.run(
        appeal_review_flow.AppealReviewMixin().on_decision(
            _fake_update(query, 7),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
    assert query.answers[-1] == (
        t("appeals.review.not_authorized", "en-US", plain=True),
        True,
    )
    assert query.edits == []


def _wire_approve(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Wire the approve path with recording doubles; returns the recorders."""
    record: dict[str, Any] = {"demoted": [], "deactivated": []}

    async def _groups() -> list[Any]:
        return []

    async def _fname(user_id: int, fallback: str = "") -> str:
        return fallback

    async def _deactivate(target_id: int) -> int:
        record["deactivated"].append(target_id)
        return 1

    async def _clear(ban_id: str) -> None:
        return None

    async def _locale_update(update: Any) -> str:
        return "en-US"

    async def _locale_user(user_id: int) -> str:
        return "en-US"

    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.users_cache, "get_first_name", _fname)
    monkeypatch.setattr(db.bans_db, "deactivate_all_active_bans", _deactivate)
    monkeypatch.setattr(db.bans_db, "clear_review", _clear)
    monkeypatch.setattr(appeal_review_flow, "locale_for_update", _locale_update)
    monkeypatch.setattr(appeal_review_flow, "locale_for_user", _locale_user)
    return record


def _run_approve(query: _FakeQuery, approver_role: str = "founder") -> None:
    """Run the approve executor against a staff-banned target."""
    admin = type("Admin", (), {"id": 1, "first_name": "Admin"})()
    ban: dict[str, Any] = {
        "ban_id": "abc",
        "is_active": True,
        "review_message_id": 1,
        "review_timestamp": datetime.now(UTC),
        "actor_user_id": 1,
        "target_user_id": 9,
        "rejected_at": None,
        "appeal_link": "",
        "appeal_submitted_at": None,
        "appeal_log_msg_id": 0,
    }
    mixin = appeal_review_flow.AppealVerdictsMixin()
    mixin.community_name = "Test"
    asyncio.run(
        mixin._approve_appeal(
            _FakeBot(),  # type: ignore[arg-type]
            query,  # type: ignore[arg-type]
            ban,  # type: ignore[arg-type]
            "abc",
            9,
            admin,  # type: ignore[arg-type]
            0,
            None,
            _fake_update(query, 1),  # type: ignore[arg-type]
            approver_role=approver_role,
        )
    )


def test_approve_demotes_staff_before_deactivate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _wire_approve(monkeypatch)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin" if user_id == 9 else "founder"

    async def _fake_demote(
        bot: Any,
        target_id: int,
        target_fname: str,
        target_role: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str | None = None,
    ) -> bool:
        record["demoted"].append((target_id, target_role))
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query)

    assert record["demoted"] == [(9, "admin")]
    assert record["deactivated"] == [9]


def test_approve_blocks_when_demote_is_a_noop_and_the_role_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op demote that leaves the role live must block the unban.

    The /tcunban path already aborted here. The appeal path used to ignore
    the demote result and unban a user who still held federation rank.
    """
    record = _wire_approve(monkeypatch)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin" if user_id == 9 else "founder"

    async def _fake_demote(*a: Any, **k: Any) -> bool:
        record["demoted"].append((9, "admin"))
        return False

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query)

    assert record["demoted"] == [(9, "admin")]
    assert record["deactivated"] == []
    assert query.answers[-1] == (
        t("appeals.review.demote_blocked", "en-US", plain=True),
        True,
    )


def test_approve_blocks_when_the_demote_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing demote must block the approval and keep the ban active."""
    record = _wire_approve(monkeypatch)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin" if user_id == 9 else "founder"

    async def _fake_demote(*a: Any, **k: Any) -> bool:
        raise RuntimeError("database down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query)

    assert record["deactivated"] == []
    assert query.answers[-1] == (
        t("appeals.review.demote_blocked", "en-US", plain=True),
        True,
    )


def test_approve_blocks_when_the_approver_does_not_outrank_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approver must outrank the target before the ban is lifted.

    Approving strips the target's federation role and lifts the ban
    everywhere, which is the same irreversible action as /tcunban. That
    command path refuses an equal-rank target, so the callback path must
    refuse it too: an Admin must not strip a peer Admin's rank.
    """
    record = _wire_approve(monkeypatch)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _fake_demote(*a: Any, **k: Any) -> bool:
        record["demoted"].append((9, "admin"))
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query, approver_role="admin")

    assert record["demoted"] == []
    assert record["deactivated"] == []
    assert query.answers[-1] == (
        t("common.refuse.outranked", "en-US", role="Admin", plain=True),
        True,
    )


def test_approve_proceeds_when_the_approver_outranks_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A higher-ranked approver keeps the approval working."""
    record = _wire_approve(monkeypatch)

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin" if user_id == 9 else "founder"

    async def _fake_demote(*a: Any, **k: Any) -> bool:
        record["demoted"].append((9, "admin"))
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query, approver_role="founder")

    assert record["demoted"] == [(9, "admin")]
    assert record["deactivated"] == [9]


def test_approve_proceeds_when_the_role_is_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op demote with no live role left may proceed with the unban."""
    record = _wire_approve(monkeypatch)
    reads: list[int] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        reads.append(user_id)
        # * The approve path reads the role first and demotes it; the gate's
        # * live re-read after the no-op demote sees it already gone.
        return "admin" if len(reads) == 1 else None

    async def _fake_demote(*a: Any, **k: Any) -> bool:
        record["demoted"].append((9, "admin"))
        return False

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_fake_demote))

    query = _FakeQuery("appeal_approve_abc")
    _run_approve(query)

    assert record["deactivated"] == [9]
