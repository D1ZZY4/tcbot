# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute argument parsing when the reply target is restated before the duration."""

from __future__ import annotations

import asyncio
import inspect
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules import mute
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.scope import flow_scope
from tcbot.modules.helper.targets import ModTarget


class _Message:
    """Message double that accepts the proof prompt and carries a reply."""

    def __init__(self, first_token: str) -> None:
        self.chat = SimpleNamespace(id=-1001, type="supergroup")
        self.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=42, username="alice")
        )
        self._first_token = first_token

    async def reply_text(self, *args: Any, **kwargs: Any) -> object:
        return SimpleNamespace(message_id=7)


def _target(msg: _Message, first_token: str) -> ModTarget:
    """Return the resolved target shared by every moderation entry."""
    admin = SimpleNamespace(id=1, first_name="Admin")
    return ModTarget(
        msg=msg,  # type: ignore[arg-type]
        admin=admin,  # type: ignore[arg-type]
        locale="en-US",
        target_id=42,
        target_name="Target",
        has_explicit_target=False,
        args=[first_token, "10m", "spam"],
        ident=Identity("user", 42, "Target", "alice"),
    )


def _run(monkeypatch: pytest.MonkeyPatch, first_token: str) -> dict[str, Any]:
    """Run the command entry and return its conversation payload."""
    msg = _Message(first_token)
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
        effective_chat=msg.chat,
    )
    ctx = SimpleNamespace(user_data={})

    async def _resolve(*args: Any, **kwargs: Any) -> ModTarget:
        return _target(msg, first_token)

    monkeypatch.setattr(mute.targets, "resolve_mod_target", _resolve)

    result = asyncio.run(inspect.unwrap(mute.cmd_mute)(update, ctx))
    assert result == mute.WAITING_PROOF
    return flow_scope(ctx, update)  # type: ignore[arg-type]


@pytest.mark.parametrize("first_token", ["@Alice", "42"])
def test_a_restated_reply_target_does_not_hide_the_duration(
    monkeypatch: pytest.MonkeyPatch, first_token: str
) -> None:
    """The restatement is consumed before the duration and reason parse."""
    scope = _run(monkeypatch, first_token)

    assert scope["mute_duration"] == timedelta(minutes=10)
    assert scope["mute_reason"] == "spam"
