# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review cards survive transient database failures untouched."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.pipelines import appeal_review
from tcbot.utils.i18n import t


class _FakeQuery:
    """CallbackQuery double recording answers and edits."""

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


class _FakeUpdate:
    def __init__(self, query: _FakeQuery) -> None:
        self.callback_query = query
        self.effective_user = type("U", (), {"id": 1})()


def _expected_retry() -> str:
    return t("appeals.review.db_retry", "en-US", plain=True)


def test_a_demoted_reviewer_is_refused_at_decision_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rank lost during the decision awaits must not lift a ban."""

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "user"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    query = _FakeQuery("appeal_approve_abc_1")

    allowed = asyncio.run(
        appeal_review._decision_role_still_valid(
            query, "en-US", 7, "moderator", action="approve"
        )
    )

    assert allowed is False
    assert query.answers[-1][1] is True


def test_a_failed_reject_card_edit_queues_the_outbox_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decided appeal must not keep a card whose edit failed."""
    enqueued: list[tuple[int, int, int]] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _name(user_id: int, fallback: str | None = None) -> str:
        return "Target"

    async def _locale(update: object) -> str:
        return "en-US"

    async def _user_locale(user_id: int) -> str:
        return "en-US"

    async def _ack(query: object) -> None:
        return None

    async def _broken_edit(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("card edit failed")

    async def _send_text(*args: Any, **kwargs: Any) -> None:
        return None

    async def _log(*args: Any, **kwargs: Any) -> None:
        return None

    async def _reject(ban_id: str, admin_id: int, admin_name: str) -> bool:
        return True

    async def _enqueue(action_id: int, chat_id: int, message_id: int) -> None:
        enqueued.append((action_id, chat_id, message_id))

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_cache, "get_first_name", _name)
    monkeypatch.setattr(db.bans_db, "reject_appeal", _reject)
    monkeypatch.setattr(db.notifications_db, "enqueue_review_card_edit", _enqueue)
    monkeypatch.setattr(appeal_review, "locale_for_update", _locale)
    monkeypatch.setattr(appeal_review, "locale_for_user", _user_locale)
    monkeypatch.setattr(appeal_review.guards, "outranks", lambda _a, _b: True)
    monkeypatch.setattr(appeal_review, "answer_ack", _ack)
    monkeypatch.setattr(appeal_review, "safe_edit_cb", _broken_edit)
    monkeypatch.setattr(appeal_review, "send_text", _send_text)
    monkeypatch.setattr(appeal_review, "_update_or_send_log", _log)
    monkeypatch.setattr(appeal_review, "cfg", dataclasses.replace(cfg, main_group=-100))

    admin = SimpleNamespace(id=7, first_name="Ayu")
    decided = asyncio.run(
        appeal_review.RejectMixin()._reject_appeal(
            SimpleNamespace(),
            SimpleNamespace(),
            _FakeQuery("appeal_reject_abc_1"),
            {"id": 5, "review_message_id": 900},
            "abc",
            42,
            admin,  # type: ignore[arg-type]
            123,
            None,
        )
    )

    assert decided is True
    assert enqueued == [(5, -100, 900)]


def test_ban_read_failure_alerts_and_keeps_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _boom(ban_id: str) -> object:
        raise RuntimeError("db blip")

    async def _locale(update: object) -> str:
        return "en-US"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.bans_db, "get_ban", _boom)
    monkeypatch.setattr(appeal_review, "locale_for_update", _locale)

    query = _FakeQuery("appeal_approve_abc_1")
    asyncio.run(
        appeal_review.AppealReviewMixin().on_decision(
            _FakeUpdate(query),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )

    assert query.answers[-1] == (_expected_retry(), True)
    assert query.edits == []
