# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared approval cards: a refused tap must leave the card actionable."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.messages import replies
from tcbot.modules.helper.pipelines import connected_flow, promo_decision_flow
from tcbot.modules.helper.pipelines.connected_flow import BuildConnection
from tcbot.utils.i18n import t


class _FakeQuery:
    """Callback query double that records answers and edits."""

    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []
        self.edits: list[str] = []
        self.markup_clears = 0

    async def answer(
        self, text: str = "", *, show_alert: bool = False, **kwargs: Any
    ) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)

    async def edit_message_reply_markup(self, *args: Any, **kwargs: Any) -> None:
        self.markup_clears += 1


def _promo_update(query: _FakeQuery, user_id: int) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id, "first_name": "Staff"})(),
        },
    )()


def _request(target_id: int) -> dict[str, Any]:
    return {
        "request_id": "req-1",
        "target_user_id": target_id,
        "first_name": "Target",
        "status": "pending",
    }


def _install_promo_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_owner: bool | BaseException,
    request: dict[str, Any] | None,
) -> None:
    async def _locale(update: Any) -> str:
        return "en-US"

    async def _owner(user_id: int, *, fresh: bool = False) -> bool:
        if isinstance(is_owner, BaseException):
            raise is_owner
        return is_owner

    async def _request_by_id(request_id: str) -> dict[str, Any] | None:
        return request

    monkeypatch.setattr(promo_decision_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.users_roles, "is_owner", _owner)
    monkeypatch.setattr(db.queues_db, "get_request_by_id", _request_by_id)


def test_promo_non_owner_tap_keeps_the_decision_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader of a shared card cannot remove the Founder's buttons."""
    _install_promo_common(monkeypatch, is_owner=False, request=_request(42))
    query = _FakeQuery("promo_approve:req-1")

    asyncio.run(
        promo_decision_flow.execute_promo_decision(
            _promo_update(query, 5),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )

    assert query.edits == []
    assert query.answers[-1] == (
        replies.perm_founder_only("en-US", plain=True),
        True,
    )


def test_promo_owner_lookup_failure_keeps_the_decision_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient lookup failure must not destroy the decision surface."""
    _install_promo_common(
        monkeypatch, is_owner=RuntimeError("db down"), request=_request(42)
    )
    query = _FakeQuery("promo_approve:req-1")

    asyncio.run(
        promo_decision_flow.execute_promo_decision(
            _promo_update(query, 5),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )

    assert query.edits == []
    assert query.answers[-1][1] is True


def test_promo_approve_refuses_the_current_founder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale request for the new owner must not rewrite the owner role."""
    _install_promo_common(monkeypatch, is_owner=True, request=_request(42))
    resolved: list[str] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str:
        return "founder"

    async def _resolve(request_id: str, status: str, resolved_by: int) -> bool:
        _ = (status, resolved_by)
        resolved.append(request_id)
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.queues_db, "resolve", _resolve)
    query = _FakeQuery("promo_approve:req-1")

    asyncio.run(
        promo_decision_flow.execute_promo_decision(
            _promo_update(query, 1),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )

    assert resolved == []
    assert query.edits == []
    assert query.answers[-1] == (
        t("admins.promote.target_is_founder", "en-US", plain=True),
        True,
    )


class _JoinBot:
    """Bot double: one membership answer, optionally raising."""

    def __init__(self, status: str | None = "member") -> None:
        self.status = status

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        if self.status is None:
            raise RuntimeError("telegram down")
        return type("Member", (), {"status": self.status})()


def _join_update(query: _FakeQuery) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_chat": type("Chat", (), {"id": -1009999999999})(),
            "effective_user": type("U", (), {"id": 5})(),
        },
    )()


def _install_join(monkeypatch: pytest.MonkeyPatch, status: str | None) -> _JoinBot:
    async def _locale(update: Any) -> str:
        return "en-US"

    bot = _JoinBot(status)
    monkeypatch.setattr(connected_flow, "locale_for_update", _locale)
    return bot


def test_join_decision_non_owner_keeps_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member who taps the shared prompt must not remove its buttons."""
    bot = _install_join(monkeypatch, "member")
    query = _FakeQuery("tc_join")

    asyncio.run(
        BuildConnection(community_name="TCF").on_join_decision(
            _join_update(query),  # type: ignore[arg-type]
            type("Ctx", (), {"bot": bot})(),  # type: ignore[arg-type]
        )
    )

    assert query.markup_clears == 0
    assert query.edits == []
    assert query.answers[-1] == (
        t("connecting.state.owner_only", "en-US", plain=True),
        True,
    )


def test_join_decision_lookup_failure_keeps_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed membership probe must not destroy the prompt either."""
    bot = _install_join(monkeypatch, None)
    query = _FakeQuery("tc_join")

    asyncio.run(
        BuildConnection(community_name="TCF").on_join_decision(
            _join_update(query),  # type: ignore[arg-type]
            type("Ctx", (), {"bot": bot})(),  # type: ignore[arg-type]
        )
    )

    assert query.markup_clears == 0
    assert query.edits == []
    assert query.answers[-1] == (
        t("connecting.state.role_check_failed", "en-US", plain=True),
        True,
    )
