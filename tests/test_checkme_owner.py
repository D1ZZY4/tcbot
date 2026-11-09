# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Checkme callbacks must not render another user's ban card."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.checking import checkme


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _update_q(uid: int, ban_id: str) -> Any:
    async def _answer(*args: Any, **kwargs: Any) -> None:
        return None

    q = SimpleNamespace(
        data=f"checkme_detail:{ban_id}",
        answer=_answer,
        from_user=SimpleNamespace(id=uid),
    )
    user = SimpleNamespace(id=uid, first_name="User", is_bot=False)
    chat = SimpleNamespace(id=-1001, type="supergroup")
    return SimpleNamespace(
        callback_query=q,
        effective_user=user,
        effective_chat=chat,
        effective_message=SimpleNamespace(chat=chat),
    )


def test_checkme_detail_refuses_other_user_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ban = {"ban_id": "b1", "banned_user_id": 22, "admin_user_id": 11, "is_active": True}

    async def _get_ban(ban_id: str) -> Any:
        return ban

    monkeypatch.setattr(db.bans_db, "get_ban", _get_ban)
    rendered: list[str] = []

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _render(ban: Any, locale: Any = None) -> tuple[str, None]:
        rendered.append("ok")
        return "ok", None

    monkeypatch.setattr(checkme, "locale_for_update", _locale)
    monkeypatch.setattr(checkme, "build_ban_detail", _render)
    update = _update_q(99, "b1")
    ctx = SimpleNamespace(bot=SimpleNamespace(username="tbot"), user_data={})
    _run(checkme.on_checkme_detail(update, ctx))  # type: ignore[arg-type]
    assert rendered == []
