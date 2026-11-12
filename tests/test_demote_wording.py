# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A demote must not claim a moderation action that never happened.

The warn threshold exempts a staff holder from the ban and demotes them
instead. The direct message must say so: the earlier wording told the
target they had been banned from the federation, and no ban was ever
issued.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.pipelines import warn_flow
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.utils.i18n import available_locales, load_catalog, t


class _FakeMessage:
    """A message that records the replies."""

    def __init__(self, chat_id: int = -1001) -> None:
        self.chat = type(
            "Chat", (), {"id": chat_id, "type": "supergroup", "title": "Group"}
        )()
        self.text = "spam"
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append(text)

    async def delete(self) -> None:
        return None


def _fake_update(message: _FakeMessage) -> Any:
    """Return an update carrying the message and the moderator."""
    return type(
        "Upd",
        (),
        {
            "effective_message": message,
            "effective_chat": message.chat,
            "effective_user": type("U", (), {"id": 1, "first_name": "Mod"})(),
        },
    )()


def _wire(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Wire the warn flow so the threshold hits a staff holder."""
    record: dict[str, Any] = {"triggers": [], "replies": []}

    async def _verdict(executor_id: int, target_id: int) -> tuple[Any, Any]:
        return decorators.EnforcementVerdict.ALLOWED, None

    async def _add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
        return cfg.warn_limit

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _locale(update: Any) -> str:
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
        record["triggers"].append(trigger)
        return True

    async def _reply(msg: Any, text: str, **kwargs: Any) -> None:
        record["replies"].append(text)

    monkeypatch.setattr(decorators, "enforcement_verdict", _verdict)
    monkeypatch.setattr(db.warns_db, "add_warn", _add_warn)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(warn_flow, "locale_for_update", _locale)
    monkeypatch.setattr(warn_flow, "safe_reply", _reply)
    monkeypatch.setattr(Demote, "execute", staticmethod(_fake_demote))
    return record


def test_the_staff_exemption_demotes_without_claiming_a_ban(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warn threshold demotes a staff holder instead of banning them."""
    record = _wire(monkeypatch)

    message = _FakeMessage()
    ctx = type("Ctx", (), {"bot": object()})()
    asyncio.run(
        warn_flow.execute_warn(
            _fake_update(message),  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
            9,
            "Staff",
            "spam",
        )
    )

    assert record["triggers"] == ["warn"]


def test_the_warn_dm_does_not_claim_a_ban() -> None:
    """The warn wording must not tell the target they were banned."""
    text = t(
        "demote.dm.warn",
        "en-US",
        role="Admin",
        community="Test",
    )
    lowered = text.lower()

    # * The false claim was "you were banned from the federation".
    assert "you were banned" not in lowered
    assert "demoted" in lowered
    assert "warning limit" in lowered


def test_the_indonesian_warn_wording_denies_the_ban() -> None:
    """The Indonesian wording must deny the ban, not assert it."""
    lowered = t(
        "demote.dm.warn",
        "id-ID",
        role="Admin",
        community="Test",
    ).lower()

    assert "tidak diblokir" in lowered
    assert "kamu diblokir" not in lowered


def test_every_locale_carries_the_warn_wording() -> None:
    """The new demote wording exists in every shipped locale."""
    catalog = load_catalog()
    for locale in available_locales(catalog):
        assert "demote.dm.warn" in catalog[locale], locale
