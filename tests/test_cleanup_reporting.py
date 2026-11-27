# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A cleanup sweep must report groups it could not verify."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules import maintenance


def test_a_failed_probe_is_named_in_the_cleanup_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []

    async def _active() -> Any:
        return [{"chat_id": -101, "title": "A"}]

    async def _role(_uid: int, *, fresh: bool = False) -> str:
        return "admin"

    async def _owner() -> int:
        return 999

    async def _locale(_ctx: Any) -> str:
        return "en-US"

    async def _reply(msg: Any, text: str, **_kwargs: Any) -> None:
        replies.append(text)

    async def _fan_out(coros: Any) -> list[object]:
        results: list[object] = []
        for coro in coros:
            coro.close()
            results.append(RuntimeError("probe timed out"))
        return results

    monkeypatch.setattr(db.groups_db, "active_groups", _active)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)
    monkeypatch.setattr(maintenance, "reply_rich", _reply)
    monkeypatch.setattr(maintenance, "fan_out", _fan_out)

    msg = SimpleNamespace(text="/tcclean", effective_message=SimpleNamespace())
    ctx = SimpleNamespace(
        bot=SimpleNamespace(),
        effective_message=msg,
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        user_data={},
    )
    asyncio.run(maintenance.cmd_cleanup(ctx))  # type: ignore[arg-type]

    assert replies
    assert "failed checking" in replies[0]
    assert "<code>1</code>" in replies[0]
