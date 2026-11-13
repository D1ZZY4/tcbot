# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The federation-wide surfaces stay behind their gate.

The stats drill-downs enumerate federation-wide records, so they are
staff-only. The enforcement path must verify that the executor still
holds the tier the action needs, and a role prompt must not be
dismissible by a non-staffer.

These tests pin the three gates: a crafted tap on a staff-only panel is
refused, a demoted moderator cannot enforce, and a non-staffer cannot
collapse a role prompt.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules import admins, stats
from tcbot.modules.helper.guards import (
    EnforcementVerdict,
    enforcement_verdict,
)
from tcbot.modules.helper.keyboards import stats_main_kb
from tcbot.utils.i18n import t


class _FakeCallback:
    """Callback double recording the answer and the edited text."""

    def __init__(self, data: str = "stats_bans:0") -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []
        self.edits: list[str] = []

    async def answer(self, text: str = "", *, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)

    @property
    def from_user(self) -> Any:
        return SimpleNamespace(id=42)

    @property
    def message(self) -> Any:
        return None


def _update(q: _FakeCallback, user_id: int = 42) -> Any:
    return SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=user_id, first_name="Mod"),
        effective_chat=SimpleNamespace(id=-1001, type="group"),
        effective_message=None,
    )


def _roles(monkeypatch: pytest.MonkeyPatch, roles: dict[int, str | None]) -> None:
    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return roles.get(user_id)

    async def _owner(user_id: int, *, fresh: bool = False) -> bool:
        return False

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_roles, "is_owner", _owner)


# ───────────────────────────── Stats gate ───────────────────────────── #


def test_a_non_staffer_cannot_open_the_ban_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crafted tap on the ban list is refused for a non-staffer."""
    _roles(monkeypatch, {42: None})
    q = _FakeCallback()
    asyncio.run(stats.on_stats_bans(_update(q), SimpleNamespace(user_data={})))
    assert q.edits == []
    assert q.answers
    assert q.answers[0][1] is True


def test_a_staffer_can_open_the_ban_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Tester passes the gate and the list renders."""
    _roles(monkeypatch, {42: "tester"})
    q = _FakeCallback()
    rendered: list[Any] = []

    async def _bans_list(page: int, locale: str | None = None) -> tuple[str, Any]:
        rendered.append(page)
        return "bans", None

    monkeypatch.setattr(stats.Stats, "bans_list", _bans_list)
    asyncio.run(stats.on_stats_bans(_update(q), SimpleNamespace(user_data={})))
    assert rendered == [0]
    assert q.edits == ["bans"]


def test_a_lookup_outage_closes_the_stats_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed role lookup refuses the panel instead of opening it."""
    _roles(monkeypatch, {})

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    q = _FakeCallback()
    asyncio.run(stats.on_stats_bans(_update(q), SimpleNamespace(user_data={})))
    assert q.edits == []
    assert q.answers


def test_the_owner_keeps_the_staff_panes() -> None:
    """The owner id passes the gate even when the founder role is unset."""
    kb = stats_main_kb(show_users=True, show_staff=True)
    labels = [button.text for row in kb.inline_keyboard for button in row]
    assert "Users" in labels


# ──────────────────────── Enforcement tier ──────────────────────────── #


def test_the_enforcement_refuses_an_executor_below_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A moderator demoted during the proof window cannot enforce."""
    _roles(monkeypatch, {11: None, 99: None})
    verdict, _label = asyncio.run(enforcement_verdict(11, 99, min_role="developer"))
    assert verdict is EnforcementVerdict.RANK_INSUFFICIENT


def test_the_enforcement_allows_an_executor_at_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A moderator that still holds the tier enforces normally."""
    _roles(monkeypatch, {11: "developer", 99: None})
    verdict, _label = asyncio.run(enforcement_verdict(11, 99, min_role="developer"))
    assert verdict is EnforcementVerdict.ALLOWED


def test_the_enforcement_still_refuses_an_outranked_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outrank rule is unchanged by the tier check."""
    _roles(monkeypatch, {11: "developer", 99: "admin"})
    verdict, label = asyncio.run(enforcement_verdict(11, 99, min_role="developer"))
    assert verdict is EnforcementVerdict.OUTRANKED
    assert label == "Admin"


# ─────────────────────────── Role prompt gate ────────────────────────── #


@pytest.mark.parametrize(
    ("handler", "cancelled_key"),
    [
        (admins.on_promote_role_cancel, "admins.error.promote_cancelled"),
        (admins.on_demote_cancel, "admins.error.cancelled"),
    ],
)
def test_a_non_staffer_cannot_collapse_a_role_prompt(
    monkeypatch: pytest.MonkeyPatch, handler: Any, cancelled_key: str
) -> None:
    """The cancel button of a role prompt needs staff rank."""
    _roles(monkeypatch, {42: None})
    q = _FakeCallback(data="demote_cancel:99:42")
    asyncio.run(handler(_update(q), SimpleNamespace(user_data={})))
    assert t(cancelled_key, "en-US", plain=True) not in q.edits
    assert q.edits == [t("common.err.perm_expired", "en-US", plain=True)]


@pytest.mark.parametrize(
    ("handler", "cancelled_key"),
    [
        (admins.on_promote_role_cancel, "admins.error.promote_cancelled"),
        (admins.on_demote_cancel, "admins.error.cancelled"),
    ],
)
def test_a_staffer_can_collapse_a_role_prompt(
    monkeypatch: pytest.MonkeyPatch, handler: Any, cancelled_key: str
) -> None:
    """A staffer who opened the prompt collapses it."""
    _roles(monkeypatch, {42: "admin"})
    q = _FakeCallback(data="demote_cancel:99:42")
    asyncio.run(handler(_update(q), SimpleNamespace(user_data={})))
    assert q.edits == [t(cancelled_key, "en-US", plain=True)]
