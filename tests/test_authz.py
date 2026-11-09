# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Executor checks fail closed and origin guards enforce federation scope."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.decorators import (
    checks,
    require_federation_origin,
    resolve_and_check,
)


def _msg(chat_type: str = "group", chat_id: int = -1001) -> Any:
    return SimpleNamespace(chat=SimpleNamespace(type=chat_type, id=chat_id))


class _ReplyLog:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def reply(self, msg: Any, text: str, **kwargs: Any) -> None:
        self.texts.append(text)


def _install(monkeypatch: pytest.MonkeyPatch, log: _ReplyLog) -> None:
    async def _locale(*args: Any) -> str:
        return "en-US"

    async def _safe_reply(msg: Any, text: str, **kwargs: Any) -> None:
        await log.reply(msg, text, **kwargs)

    monkeypatch.setattr(checks, "effective_locale", _locale)
    monkeypatch.setattr(checks, "safe_reply", _safe_reply)


def test_resolve_and_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = {11: "developer", 22: None}
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return roles.get(user_id)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    executor, target = asyncio.run(
        resolve_and_check(_msg(), 11, 22, min_role="developer")
    )
    assert (executor, target) == ("developer", None)
    assert log.texts == []


def test_resolve_and_check_fails_closed_on_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    executor, target = asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))
    assert (executor, target) == (None, None)
    # * One fail-closed retry notice, not a silent pass.
    assert len(log.texts) == 1


def test_resolve_and_check_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _cancelled(user_id: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_effective_role", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))


def test_resolve_and_check_rejects_outrank_and_low_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "tester" if user_id == 11 else "admin"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    # * Tester (rank 1) outranked by admin target (rank 3): refuse.
    executor, target = asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))
    assert (executor, target) == (None, None)
    assert len(log.texts) == 1


def test_require_origin_allows_private_only_when_permitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    msg = _msg(chat_type="private", chat_id=42)
    assert (
        asyncio.run(
            require_federation_origin(
                msg, chat_id=42, chat_type="private", locale="en-US", allow_private=True
            )
        )
        is True
    )
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=42,
                chat_type="private",
                locale="en-US",
                allow_private=False,
            )
        )
        is False
    )
    assert len(log.texts) == 1


def test_require_origin_blocks_disconnected_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    msg = _msg(chat_type="group", chat_id=-1002)

    async def _not_connected(chat_id: int, *, fresh: bool = False) -> bool:
        return False

    monkeypatch.setattr(db.groups_db, "is_connected", _not_connected)
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=-1002,
                chat_type="group",
                locale="en-US",
                allow_private=True,
            )
        )
        is False
    )

    async def _boom(chat_id: int, *, fresh: bool = False) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.groups_db, "is_connected", _boom)
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=-1002,
                chat_type="group",
                locale="en-US",
                allow_private=True,
            )
        )
        is False
    )
    assert len(log.texts) == 2


def test_recheck_executor_rank_allows_meeting_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "developer"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="developer"))
        is True
    )
    assert log.texts == []


def test_recheck_executor_rank_refuses_demotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return None

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))
        is False
    )
    assert len(log.texts) == 1


def test_recheck_executor_rank_fails_closed_on_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))
        is False
    )
    assert len(log.texts) == 1


def test_recheck_executor_rank_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _cancelled(user_id: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_effective_role", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))
