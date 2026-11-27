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
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest


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


@pytest.mark.asyncio
async def test_a_gone_chat_api_refusal_prunes_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHAT_NOT_FOUND means the bot is gone, not that the group is healthy."""

    class _Bot:
        async def get_chat_member(self, _chat_id: int, _user_id: int) -> None:
            raise BadRequest("Telegram says: [400 CHAT_NOT_FOUND] - chat not found")

    async def _identity(_bot: object) -> object:
        return SimpleNamespace(id=42)

    monkeypatch.setattr(maintenance, "bot_identity", _identity)

    assert await maintenance._should_remove(_Bot(), {"chat_id": -101}) is True


@pytest.mark.asyncio
async def test_an_unrelated_api_refusal_keeps_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambiguous service refusal must not prune a live group."""

    class _Bot:
        async def get_chat_member(self, _chat_id: int, _user_id: int) -> None:
            raise BadRequest("Telegram says: [400 SOMETHING_ELSE] - retry")

    async def _identity(_bot: object) -> object:
        return SimpleNamespace(id=42)

    monkeypatch.setattr(maintenance, "bot_identity", _identity)

    assert await maintenance._should_remove(_Bot(), {"chat_id": -101}) is False
