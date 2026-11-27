# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The demote confirmation re-reads both ranks before removing a role."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules import admins
from tcbot.modules.helper.identity import Identity


class _FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []

    async def answer(
        self, text: str = "", *, show_alert: bool = False, **kwargs: Any
    ) -> None:
        self.answers.append((text, show_alert))


def _update(query: _FakeQuery, user_id: int) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id})(),
        },
    )()


def test_demote_confirm_refuses_target_promoted_during_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target promoted from moderator to Admin cannot be stripped by an Admin.

    The confirmation card stays live while awaits run. The first role read
    saw a moderator, but the authoritative read at the mutation point sees an
    Admin, and removing that tier is reserved for the Owner.
    """

    async def _locale(ctx: Any) -> str:
        return "en-US"

    async def _owner_mismatch(q: Any, ctx: Any, *, min_parts: int) -> bool:
        return False

    async def _executor(ctx: Any, q: Any, admin: Any) -> str:
        return "admin"

    target_reads = 0

    async def _role(user_id: int, *, fresh: bool) -> str:
        nonlocal target_reads
        if user_id == 7:
            target_reads += 1
            return "moderator" if target_reads == 1 else "admin"
        return "admin"

    async def _mention(uid: int) -> tuple[str, None]:
        return "Target", None

    async def _classify(
        bot: Any, executor_id: int, target_id: int, fname: str | None = None, **kw: Any
    ) -> Identity:
        return Identity("admin", target_id, fname or "Target")

    async def _no_demote(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("Demote.execute must not run for a peer Admin")

    edits: list[str] = []

    async def _edit(q: Any, text: str, **kwargs: Any) -> None:
        edits.append(text)

    monkeypatch.setattr(admins, "locale_for_update", _locale)
    monkeypatch.setattr(admins, "action_owner_mismatch", _owner_mismatch)
    monkeypatch.setattr(admins, "check_callback_executor", _executor)
    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(admins.db.users_cache, "get_user_mention_data", _mention)
    monkeypatch.setattr(admins.identity, "classify", _classify)
    monkeypatch.setattr(admins.Demote, "execute", _no_demote)
    monkeypatch.setattr(admins, "cb_error_edit", _edit)

    query = _FakeQuery("demote_confirm:7:2")
    asyncio.run(
        admins.on_demote_confirm(_update(query, 2), None)  # type: ignore[arg-type]
    )

    assert target_reads == 2
    assert edits
    assert query.answers == []


def test_demote_confirm_refuses_an_executor_demoted_during_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor's rank is re-read too, not only the target's."""

    async def _locale(ctx: Any) -> str:
        return "en-US"

    async def _owner_mismatch(q: Any, ctx: Any, *, min_parts: int) -> bool:
        return False

    async def _executor(ctx: Any, q: Any, admin: Any) -> str:
        # * Rank at callback entry; the mutation-point read is lower.
        return "admin"

    async def _role(user_id: int, *, fresh: bool) -> str:
        if user_id == 2:
            return "moderator"
        return "moderator"

    async def _mention(uid: int) -> tuple[str, None]:
        return "Target", None

    async def _classify(
        bot: Any, executor_id: int, target_id: int, fname: str | None = None, **kw: Any
    ) -> Identity:
        return Identity("moderator", target_id, fname or "Target")

    async def _no_demote(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("Demote.execute must not run for a demoted executor")

    edits: list[str] = []

    async def _edit(q: Any, text: str, **kwargs: Any) -> None:
        edits.append(text)

    monkeypatch.setattr(admins, "locale_for_update", _locale)
    monkeypatch.setattr(admins, "action_owner_mismatch", _owner_mismatch)
    monkeypatch.setattr(admins, "check_callback_executor", _executor)
    monkeypatch.setattr(admins.db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(admins.db.users_cache, "get_user_mention_data", _mention)
    monkeypatch.setattr(admins.identity, "classify", _classify)
    monkeypatch.setattr(admins.Demote, "execute", _no_demote)
    monkeypatch.setattr(admins, "cb_error_edit", _edit)

    query = _FakeQuery("demote_confirm:7:2")
    asyncio.run(
        admins.on_demote_confirm(_update(query, 2), None)  # type: ignore[arg-type]
    )

    assert edits
    assert query.answers == []
