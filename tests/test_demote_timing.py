# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The demote must land when the action is enforced, not when it starts.

The reason and proof steps of the ban, kick, and mute flows are still
cancelable. A demote that ran at the entry stripped the target's
federation role, posted a federation log, and told the target they were
banned, muted, or kicked. Cancelling the flow then left all three side
effects in place with no action behind them: the target had lost their
rank and had been told they were banned without a single ban existing.

The demote therefore runs at enforcement time, next to the Telegram
fan-out it protects. These tests pin both halves of that contract.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules import kick as kicking
from tcbot.modules.helper import decorators
from tcbot.modules.helper.decorators.checks import ModTarget
from tcbot.modules.helper.pipelines import demote_flow, kick_flow


class _FakeChat:
    id = -100123
    type = "supergroup"
    title = "chat"


class _FakeUser:
    id = 111
    first_name = "Admin"
    username = "admin"


class _FakeMsg:
    text = "/tckick 999 spam"

    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.reply_to_message = None
        self.entities: tuple = ()
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> Any:
        self.replies.append(text)
        return type("Sent", (), {"message_id": 42})()


class _FakeUpdate:
    def __init__(self, msg: _FakeMsg) -> None:
        self.effective_message = msg
        self.effective_user = _FakeUser()
        self.effective_chat = _FakeChat()
        self.callback_query = None


class _FakeCtx:
    def __init__(self) -> None:
        self.user_data: dict[str, Any] = {}
        self.bot = None


def _resolved_target(msg: _FakeMsg) -> ModTarget:
    """Return a resolved target that holds a federation role."""
    ident = type("Ident", (), {"kind": "user", "is_bot": False})()
    return ModTarget(
        msg=msg,  # type: ignore[arg-type]
        admin=_FakeUser(),  # type: ignore[arg-type]
        locale="en-US",
        target_id=999,
        target_name="Target",
        has_explicit_target=True,
        args=["/tckick", "999", "spam"],
        ident=ident,  # type: ignore[arg-type]
    )


def test_the_kick_entry_does_not_demote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting a kick must not touch the target's federation role."""
    demoted: list[Any] = []

    async def _demote(*args: Any, **kwargs: Any) -> bool:
        demoted.append(args)
        return True

    async def _resolve(*args: Any, **kwargs: Any) -> ModTarget:
        return _resolved_target(args[0].effective_message)

    async def _role(uid: int, *, fresh: bool = False) -> str:
        return "tester"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(decorators, "resolve_mod_target", _resolve)
    monkeypatch.setattr(demote_flow.Demote, "execute", staticmethod(_demote))

    msg = _FakeMsg()
    ctx = _FakeCtx()
    outcome = asyncio.run(kicking.cmd_kick(_FakeUpdate(msg), ctx))  # type: ignore[arg-type]

    # * The handler ran: the proof prompt was sent.
    assert msg.replies
    assert outcome != ConversationHandler.END
    assert demoted == []


def test_the_kick_executor_demotes_before_the_fan_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enforcement path removes the role before the kick lands."""
    order: list[str] = []

    async def _demote_before_enforcement(
        bot: Any,
        target_id: int,
        target_fname: str,
        *,
        trigger: str,
        executor_id: int = 0,
        executor_fname: str = "",
    ) -> str | None:
        order.append("demote")
        return "admin"

    monkeypatch.setattr(
        kick_flow, "demote_before_enforcement", _demote_before_enforcement
    )

    # * The kick executor writes its audit row before it enforces.
    async def _log_kick(*args: Any, **kwargs: Any) -> None:
        order.append("log_kick")
        return

    async def _unban(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(db.kicks_db, "log_kick", _log_kick)

    class _Bot:
        async def ban_chat_member(self, *args: Any, **kwargs: Any) -> None:
            order.append("ban")
            return

        async def unban_chat_member(self, *args: Any, **kwargs: Any) -> None:
            return None

    update = _FakeUpdate(_FakeMsg())
    update.effective_chat = _FakeChat()  # type: ignore[assignment]
    ctx = _FakeCtx()
    ctx.bot = _Bot()  # type: ignore[assignment]

    asyncio.run(
        kick_flow.execute_kick(
            update,  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
            999,
            "Target",
            "spam",
        )
    )

    # * The demote must land before the ban, not after it: a role-holding
    # * target that is banned first keeps federation rank for the whole
    # * window between the two calls.
    assert order == ["log_kick", "demote", "ban"]
