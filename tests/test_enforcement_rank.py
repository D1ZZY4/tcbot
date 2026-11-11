# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The enforcement path re-checks the executor against the target.

The entry command compares the two roles, but the reason and proof steps
stay open for a minute. A target promoted in that window would otherwise
be actioned by a moderator who no longer outranks them, and the rule that
refused the action at entry would be silently bypassed.

These tests pin the enforcement-time check: it refuses a target who
outranks the executor, it fails closed when the role lookup fails, and it
refuses before anything is recorded.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper import decorators, identity
from tcbot.modules.helper.decorators.checks import EnforcementVerdict
from tcbot.modules.helper.pipelines import ban_flow, kick_flow


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


def _roles(monkeypatch: pytest.MonkeyPatch, executor: str | None, target: str | None):
    """Pin the effective role of the executor and of the target."""
    calls: list[tuple[int, bool]] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        calls.append((user_id, fresh))
        return executor if user_id == 111 else target

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    return calls


# ────────────────────────── The verdict helper ───────────────────────── #


async def test_the_verdict_allows_an_executor_above_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A developer may act on a regular user."""
    _roles(monkeypatch, "developer", None)

    verdict, label = await decorators.enforcement_verdict(111, 999)

    assert verdict is EnforcementVerdict.ALLOWED
    assert label is None


async def test_the_verdict_refuses_a_target_who_outranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A developer may not act on an admin."""
    _roles(monkeypatch, "developer", "admin")

    verdict, label = await decorators.enforcement_verdict(111, 999)

    assert verdict is EnforcementVerdict.OUTRANKED
    assert label == "Admin"


async def test_the_verdict_refuses_a_target_of_equal_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equal rank is refused, exactly like the entry check does."""
    _roles(monkeypatch, "admin", "admin")

    verdict, _label = await decorators.enforcement_verdict(111, 999)

    assert verdict is EnforcementVerdict.OUTRANKED


async def test_the_verdict_reads_both_roles_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check must not run on a cached role."""
    calls = _roles(monkeypatch, "developer", None)

    await decorators.enforcement_verdict(111, 999)

    assert calls == [(111, True), (999, True)]


async def test_the_verdict_fails_closed_on_a_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role lookup that fails refuses the enforcement."""

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)

    verdict, label = await decorators.enforcement_verdict(111, 999)

    assert verdict is EnforcementVerdict.LOOKUP_FAILED
    assert label is None


# ───────────────────────── The identity classification ─────────────────── #


async def test_the_classification_reads_the_role_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The protected-target refusal table must not run on a cached role.

    The refusal table is keyed on the identity kind, so a cached role
    could show a Founder as an ordinary user for the whole cache TTL and
    let the action reach its prompt.
    """
    calls: list[bool] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        calls.append(fresh)
        return "founder"

    async def _name(user_id: int) -> tuple[str, str | None]:
        return ("Founder", None)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_cache, "get_user_mention_data", _name)

    bot = SimpleNamespace(id=999)
    ident = await identity.classify(bot, 111, 222)  # type: ignore[arg-type]

    assert ident.kind == "founder"
    assert calls == [True]


# ─────────────────────────── The kick executor ─────────────────────── #


def _install_kick_doubles(
    monkeypatch: pytest.MonkeyPatch, order: list[str]
) -> _FakeCtx:
    """Record the calls the kick executor makes; return its context."""

    async def _log_kick(*args: Any, **kwargs: Any) -> None:
        order.append("log_kick")

    async def _demote(*args: Any, **kwargs: Any) -> str | None:
        order.append("demote")
        return None

    async def _unban(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(db.kicks_db, "log_kick", _log_kick)
    monkeypatch.setattr(kick_flow, "demote_before_enforcement", _demote)

    class _Bot:
        async def ban_chat_member(self, *args: Any, **kwargs: Any) -> None:
            order.append("ban")

        async def unban_chat_member(self, *args: Any, **kwargs: Any) -> None:
            return None

    ctx = _FakeCtx()
    ctx.bot = _Bot()  # type: ignore[assignment]
    return ctx


def test_the_kick_executor_refuses_a_target_who_outranks(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A promoted target is not kicked, and no audit row is written."""
    order: list[str] = []
    ctx = _install_kick_doubles(monkeypatch, order)
    _roles(monkeypatch, "developer", "admin")

    msg = _FakeMsg()
    update = _FakeUpdate(msg)

    with caplog.at_level(logging.WARNING, logger="tcbot.modules.helper.pipelines"):
        asyncio.run(
            kick_flow.execute_kick(
                update,  # type: ignore[arg-type]
                ctx,  # type: ignore[arg-type]
                999,
                "Target",
                "spam",
            )
        )

    # * Nothing was recorded and nothing was enforced.
    assert order == []
    assert any("Kick refused" in line for line in caplog.messages)


def test_the_kick_executor_refuses_on_a_role_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role lookup that fails refuses the kick."""
    order: list[str] = []
    ctx = _install_kick_doubles(monkeypatch, order)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)

    msg = _FakeMsg()
    update = _FakeUpdate(msg)

    asyncio.run(
        kick_flow.execute_kick(
            update,  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
            999,
            "Target",
            "spam",
        )
    )

    assert order == []


# ──────────────────────────── The ban executor ──────────────────────── #


def _ban_meta() -> dict[str, Any]:
    return {
        "ban_target_id": 999,
        "ban_target_fname": "Target",
        "ban_reason": "spam",
        "ban_admin_id": 111,
        "ban_admin_fname": "Mod",
        "ban_prompt_msg_id": 1,
        "ban_prompt_chat_id": 2,
        "ban_locale": "en",
    }


def test_the_ban_executor_refuses_a_target_who_outranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A promoted target is not banned, and no ban row is written."""
    _roles(monkeypatch, "developer", "admin")
    written: list[Any] = []

    async def _create_ban(*args: Any, **kwargs: Any) -> Any:
        written.append(args)
        raise AssertionError("the ban must not be created")

    monkeypatch.setattr(ban_flow.db.bans_db, "create_ban", _create_ban)

    class _Bot:
        username = "testbot"

        async def edit_message_text(self, *args: Any, **kwargs: Any) -> Any:
            return None

    asyncio.run(ban_flow._execute_ban(_Bot(), [], _ban_meta()))  # type: ignore[arg-type]

    assert written == []
