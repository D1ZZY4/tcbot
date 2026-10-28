# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review cards survive transient database failures untouched."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import appeal_review_flow
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


def test_ban_read_failure_alerts_and_keeps_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _role(user_id: int) -> str:
        return "admin"

    async def _boom(ban_id: str) -> object:
        raise RuntimeError("db blip")

    async def _locale(update: object) -> str:
        return "en-US"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.bans_db, "get_ban", _boom)
    monkeypatch.setattr(appeal_review_flow, "locale_for_update", _locale)

    query = _FakeQuery("appeal_approve_abc")
    asyncio.run(
        appeal_review_flow.AppealReviewMixin().on_decision(
            _FakeUpdate(query),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )

    assert query.answers[-1] == (_expected_retry(), True)
    assert query.edits == []
