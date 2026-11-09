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
from tcbot.modules.helper.workflows import appeal_review_flow
from tcbot.modules.helper.workflows.appeal_review_flow import verdicts
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
        "admin_user_id": 7,
        "banned_user_id": 7,
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


def test_approve_demotes_staff_before_deactivate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demoted: list[tuple[int, str]] = []
    deactivated: list[int] = []

    async def _groups() -> list[Any]:
        return []

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin" if user_id == 9 else "founder"

    async def _fname(user_id: int, fallback: str = "") -> str:
        return fallback

    async def _deactivate(target_id: int) -> int:
        deactivated.append(target_id)
        return 1

    async def _clear(ban_id: str) -> None:
        return None

    async def _locale_update(update: Any) -> str:
        return "en-US"

    async def _locale_user(user_id: int) -> str:
        return "en-US"

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
        demoted.append((target_id, target_role))
        return True

    class _FakeBot:
        async def send_message(self, *a: Any, **k: Any) -> Any:
            return type("M", (), {"message_id": 1})()

        async def unban_chat_member(self, *a: Any, **k: Any) -> None:
            return None

        async def edit_message_text(self, *a: Any, **k: Any) -> None:
            return None

    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_cache, "get_first_name", _fname)
    monkeypatch.setattr(db.bans_db, "deactivate_all_active_bans", _deactivate)
    monkeypatch.setattr(db.bans_db, "clear_review", _clear)
    monkeypatch.setattr(verdicts.Demote, "execute", staticmethod(_fake_demote))
    monkeypatch.setattr(verdicts.flow_pkg, "locale_for_update", _locale_update)
    monkeypatch.setattr(verdicts.flow_pkg, "locale_for_user", _locale_user)

    query = _FakeQuery("appeal_approve_abc")
    admin = type("Admin", (), {"id": 1, "first_name": "Admin"})()
    ban: dict[str, Any] = {
        "ban_id": "abc",
        "is_active": True,
        "review_message_id": 1,
        "review_timestamp": datetime.now(UTC),
        "admin_user_id": 1,
        "banned_user_id": 9,
        "rejected_at": None,
        "appeal_link": "",
        "appeal_submitted_at": None,
        "appeal_log_msg_id": 0,
    }
    mixin = verdicts.AppealVerdictsMixin()
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
        )
    )
    assert demoted == [(9, "admin")]
    assert deactivated == [9]
