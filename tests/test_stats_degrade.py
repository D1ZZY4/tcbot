# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A failed stats render must show an error card, not leave a dead panel."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines.stats_panels import Stats
from tcbot.modules.helper.rich.edit_msg import ack_and_render


class _Query:
    """Minimal callback query that records answers and rich edits."""

    def __init__(self) -> None:
        self.answers: list[Any] = []
        self.edits: list[dict[str, Any]] = []

    async def answer(self, *args: Any, **kwargs: Any) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> None:
        self.edits.append({"args": args, "kwargs": kwargs})


@pytest.mark.asyncio
async def test_a_failed_render_shows_the_fallback_card() -> None:
    q = _Query()

    async def _fail() -> None:
        raise RuntimeError("database unavailable")

    await ack_and_render(q, _fail(), fallback=("Could not load this view.", None))  # type: ignore[arg-type]

    assert len(q.answers) == 1
    assert len(q.edits) == 1
    edit = q.edits[0]
    payload = edit["kwargs"].get("rich_message")
    rendered = payload.html if payload is not None else str(edit["args"])
    assert "Could not load this view." in rendered


@pytest.mark.asyncio
async def test_cancellation_is_never_rendered_as_an_error_card() -> None:
    q = _Query()

    async def _cancel() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await ack_and_render(q, _cancel(), fallback=("Could not load this view.", None))  # type: ignore[arg-type]

    assert len(q.answers) == 1
    assert q.edits == []


@pytest.mark.asyncio
async def test_a_failed_count_is_marked_unavailable_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed read must not be presented as a real zero or a missing Owner."""

    async def _owner() -> int:
        return 7

    async def _admins() -> int:
        return 2

    async def _role_count(role: str) -> int:
        if role == "developer":
            raise RuntimeError("database unavailable")
        return 1

    async def _bans() -> int:
        return 4

    async def _groups() -> int:
        return 3

    async def _users() -> int:
        return 100

    async def _mention(uid: int) -> tuple[str, str | None]:
        return "Owner", None

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "admin_count", _admins)
    monkeypatch.setattr(db.users_roles, "role_count", _role_count)
    monkeypatch.setattr(db.bans_db, "active_ban_count", _bans)
    monkeypatch.setattr(db.groups_db, "active_group_count", _groups)
    monkeypatch.setattr(db.users_cache, "total_users", _users)
    monkeypatch.setattr(db.users_cache, "get_user_mention_data", _mention)

    text, _btn = await Stats.main(locale="en-US")

    assert "Unavailable" in text
    assert "<td>2</td>" in text
    assert "<td>4</td>" in text
    assert "<footer>" in text
    assert "Could not be verified" not in text
    assert "totals above" not in text
