# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cancel ownership: only the prompt opener may collapse role pickers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.admins.demote import on_demote_cancel
from tcbot.modules.admins.promote import on_promote_role_cancel
from tcbot.modules.helper import keyboards as kb
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


def _update(query: _FakeQuery, user_id: int) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id})(),
        },
    )()


def _cells(markup: Any) -> list[list[tuple[Any, Any, Any, Any]]]:
    return [
        [(b.text, b.callback_data, b.url, b.to_dict().get("style")) for b in row]
        for row in markup.inline_keyboard
    ]


def test_keyboards_carry_executor_for_cancel() -> None:
    promote_rows = _cells(
        kb.promote_role_kb(7, ["admin"], "en-US", 1),
    )
    assert promote_rows[-1][0][1] == "promo_role_cancel:7:1"
    demote_rows = _cells(kb.demote_confirm_kb(7, "en-US", 1))
    assert demote_rows[0][1][1] == "demote_cancel:7:1"


def test_non_owner_cancel_alerts_and_keeps_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr("tcbot.modules.admins.promote.locale_for_update", _locale)
    query = _FakeQuery("promo_role_cancel:7:1")
    asyncio.run(on_promote_role_cancel(_update(query, 2), None))  # type: ignore[arg-type]
    assert query.answers[-1] == (
        t("admins.error.not_prompt_owner", "en-US", plain=True),
        True,
    )
    assert query.edits == []


def test_owner_cancel_collapses_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr("tcbot.modules.admins.demote.locale_for_update", _locale)
    query = _FakeQuery("demote_cancel:7:1")
    asyncio.run(on_demote_cancel(_update(query, 1), None))  # type: ignore[arg-type]
    assert query.edits != []


def test_legacy_cancel_keeps_working(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr("tcbot.modules.admins.demote.locale_for_update", _locale)
    query = _FakeQuery("demote_cancel:7")
    asyncio.run(on_demote_cancel(_update(query, 2), None))  # type: ignore[arg-type]
    assert query.edits != []
