# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A fail-closed join never leaves a member banned without a repair run."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules import greeting
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest


class _Bot:
    """Fake bot whose ban and unban calls can be scripted."""

    def __init__(
        self, ban_error: BaseException | None, unban_errors: list[BaseException | None]
    ) -> None:
        self.ban_error = ban_error
        self.unban_errors = list(unban_errors)
        self.bans: list[tuple[int, int]] = []
        self.unbans: list[tuple[int, int]] = []

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.bans.append((chat_id, user_id))
        if self.ban_error is not None:
            raise self.ban_error

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.unbans.append((chat_id, user_id))
        error = self.unban_errors.pop(0) if self.unban_errors else None
        if error is not None:
            raise error


def _wire(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"kicks": [], "runs": []}

    async def _kick(user_id: int, chat_id: int, actor: int, reason: str) -> int:
        seen["kicks"].append((user_id, chat_id, actor, reason))
        return 7

    async def _queue(action_id: int, chat_id: int, actor: int) -> int:
        seen["runs"].append((action_id, chat_id, actor))
        return 9

    monkeypatch.setattr(db.kicks_db, "log_repair_kick", _kick)
    monkeypatch.setattr(db.enforcement_ledger, "queue_kick_unban_repair", _queue)
    return seen


@pytest.mark.asyncio
async def test_a_clean_fail_closed_removal_needs_no_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    bot = _Bot(None, [None])

    await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert bot.bans == [(-100, 42)]
    assert bot.unbans == [(-100, 42)]
    assert seen == {"kicks": [], "runs": []}


@pytest.mark.asyncio
async def test_a_failed_ban_never_queues_a_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    bot = _Bot(RuntimeError("ban refused"), [])

    await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert bot.bans == [(-100, 42)]
    assert bot.unbans == []
    assert seen == {"kicks": [], "runs": []}


@pytest.mark.asyncio
async def test_a_transient_unban_is_retried_without_a_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    bot = _Bot(None, [RuntimeError("stalled"), None])

    await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert len(bot.unbans) == 2
    assert seen == {"kicks": [], "runs": []}


@pytest.mark.asyncio
async def test_a_stranded_member_gets_a_durable_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    bot = _Bot(None, [RuntimeError("stalled"), RuntimeError("still stalled")])

    await greeting._fail_closed_join(bot, -100, 42, "join_request_approved")  # type: ignore[arg-type]

    assert len(bot.unbans) == 2
    assert len(seen["kicks"]) == 1
    assert seen["kicks"][0][0:2] == (42, -100)
    assert seen["runs"] == [(7, -100, seen["kicks"][0][2])]


@pytest.mark.asyncio
async def test_a_benign_refusal_needs_no_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    refusal = BadRequest("USER_NOT_PARTICIPANT")
    bot = _Bot(None, [refusal, refusal])

    await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert seen == {"kicks": [], "runs": []}


@pytest.mark.asyncio
async def test_cancellation_after_the_ban_still_queues_a_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)
    bot = _Bot(None, [asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert len(seen["kicks"]) == 1
    assert len(seen["runs"]) == 1


@pytest.mark.asyncio
async def test_a_repair_queue_outage_does_not_hide_the_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)

    async def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db.kicks_db, "log_repair_kick", _fail)
    bot = _Bot(None, [RuntimeError("stalled"), RuntimeError("still stalled")])

    await greeting._fail_closed_join(bot, -100, 42, "new_member")  # type: ignore[arg-type]

    assert len(bot.unbans) == 2
