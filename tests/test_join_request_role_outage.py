# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join requests fail closed when the protected-owner lookup is unavailable."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules import greeting


class _Bot:
    def __init__(self) -> None:
        self.declined: list[tuple[int, int]] = []

    async def decline_chat_join_request(self, chat_id: int, user_id: int) -> None:
        self.declined.append((chat_id, user_id))


def _ctx(bot: _Bot) -> SimpleNamespace:
    request = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=42, is_bot=False),
    )
    return SimpleNamespace(
        bot=bot,
        chat_join_request=request,
        effective_user=request.from_user,
        effective_chat=request.chat,
    )


@pytest.mark.asyncio
async def test_a_failed_owner_lookup_declines_the_join_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unverified owner must not leave the request pending for approval."""

    async def _in_federation(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def _role(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("role store unavailable")

    monkeypatch.setattr(greeting, "_in_federation", _in_federation)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    bot = _Bot()

    await greeting.on_join_request(_ctx(bot))  # type: ignore[arg-type]

    assert bot.declined == [(-1001, 42)]


@pytest.mark.asyncio
async def test_a_failed_owner_lookup_keeps_the_request_when_decline_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Telegram refusal during the decline must not hide the original outage."""

    async def _in_federation(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def _role(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("role store unavailable")

    attempts: list[tuple[int, int]] = []

    async def _decline(chat_id: int, user_id: int) -> None:
        attempts.append((chat_id, user_id))
        raise RuntimeError("decline refused")

    monkeypatch.setattr(greeting, "_in_federation", _in_federation)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    bot = _Bot()
    monkeypatch.setattr(bot, "decline_chat_join_request", _decline)

    await greeting.on_join_request(_ctx(bot))  # type: ignore[arg-type]

    assert attempts == [(-1001, 42)]


@pytest.mark.asyncio
async def test_a_verified_owner_request_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner exemption still applies when the role read succeeds."""

    async def _in_federation(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def _role(*_args: Any, **_kwargs: Any) -> str:
        return "owner"

    monkeypatch.setattr(greeting, "_in_federation", _in_federation)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    bot = _Bot()

    await greeting.on_join_request(_ctx(bot))  # type: ignore[arg-type]

    assert bot.declined == []
