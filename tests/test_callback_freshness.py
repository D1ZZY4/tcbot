# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Stale buttons must not act on a newer moderation flow."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot.modules.helper.pipelines import ban_actions
from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    _ModActionFlow,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof
from tcbot.modules.helper.scope import callback_is_current, flow_scope

_CHAT = -100
_USER = 7
_LIVE_ID = 55


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for Telegram calls that a stale tap must never reach."""


def _make(
    update_id: int, *, prompt_id: int = _LIVE_ID
) -> tuple[Any, Any, dict[str, Any]]:
    """Build a callback update whose scope records the live prompt id."""
    answered: list[bool] = []

    async def _answer() -> None:
        answered.append(True)

    query = SimpleNamespace(
        data="kick_cancel",
        message=SimpleNamespace(chat=SimpleNamespace(id=_CHAT), message_id=update_id),
        answer=_answer,
        edit_message_text=_noop,
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=_CHAT),
        effective_user=SimpleNamespace(id=_USER, first_name="Mod"),
        effective_message=None,
    )
    ctx = SimpleNamespace(user_data={})
    scope = flow_scope(cast("Any", ctx), cast("Any", update))
    scope.update(
        {
            "kick_prompt_chat": _CHAT,
            "kick_prompt_id": prompt_id,
            "kick_target_id": 99,
            "ban_prompt_chat_id": _CHAT,
            "ban_prompt_msg_id": prompt_id,
            "ban_target_id": 99,
        }
    )
    return (
        cast("Any", update),
        cast("Any", ctx),
        {"scope": scope, "answered": answered},
    )


def test_prompt_identity_decides_whether_a_callback_is_current() -> None:
    """A tap from another message is stale; an absent identity stays permissive."""
    update, _ctx, details = _make(_LIVE_ID)
    scope = details["scope"]
    kwargs = {"chat_key": "kick_prompt_chat", "message_key": "kick_prompt_id"}

    assert callback_is_current(update, scope, **kwargs) is True
    assert callback_is_current(_make(_LIVE_ID + 1)[0], scope, **kwargs) is False
    assert callback_is_current(update, {}, **kwargs) is True


def test_stale_cancel_does_not_end_a_new_kick_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A button on an old prompt cannot cancel the flow it left behind."""
    monkeypatch.setattr(
        "tcbot.modules.helper.pipelines.mod_action_steps.locale_for_update",
        _noop_locale,
    )
    flow = _ModActionFlow(
        "kick",
        BuildReason("kick", skip_allowed=False),
        BuildProof("kick", skip_allowed=False),
        _noop,
        min_role="moderator",
    )
    update, ctx, details = _make(_LIVE_ID + 1)

    result = asyncio.run(flow._on_cancel(update, ctx))

    assert result is None
    assert details["scope"]["kick_target_id"] == 99
    assert details["answered"] == [True]


def test_fresh_cancel_still_ends_the_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tap on the live prompt keeps the original cancel behaviour."""
    monkeypatch.setattr(
        "tcbot.modules.helper.pipelines.mod_action_steps.locale_for_update",
        _noop_locale,
    )
    flow = _ModActionFlow(
        "kick",
        BuildReason("kick", skip_allowed=False),
        BuildProof("kick", skip_allowed=False),
        _noop,
        min_role="moderator",
    )
    update, ctx, details = _make(_LIVE_ID)

    result = asyncio.run(flow._on_cancel(update, ctx))

    assert result == -1
    assert "kick_target_id" not in details["scope"]


def test_stale_ban_cancel_keeps_the_live_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale ban Cancel cannot clear the payload of a newer ban."""
    cancelled: list[bool] = []

    async def _cancel(_scope: Any) -> None:
        cancelled.append(True)

    monkeypatch.setattr(ban_actions, "_cancel_proof_session", _cancel)
    monkeypatch.setattr(
        "tcbot.modules.helper.pipelines.ban_actions.locale_for_update", _noop_locale
    )
    update, ctx, details = _make(_LIVE_ID + 1)

    result = asyncio.run(ban_actions.on_cancel_proof(update, ctx))

    assert result is None
    assert cancelled == []
    assert details["scope"]["ban_target_id"] == 99
    assert details["answered"] == [True]


async def _noop_locale(_update: Any) -> str:
    """Return a fixed locale for the handler under test."""
    return "en-US"
