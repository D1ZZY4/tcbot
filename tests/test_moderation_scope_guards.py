# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""State handlers must not turn ordinary group text into a target-less prompt."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation

from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.pipelines import (
    appeal_submit,
    ban_rules_step,
    ban_session,
    mod_action_steps,
    proof_session,
    proof_steps,
)
from tcbot.utils.prefixes import build_prefixed_filters


def _ctx(*, text: str | None = "an ordinary group message") -> Any:
    """Build a context double with no active moderation flow."""
    chat = SimpleNamespace(id=-100)
    msg = SimpleNamespace(text=text, chat=chat)
    return SimpleNamespace(
        user_data={},
        chat_data={},
        bot_data={},
        args=(),
        bot=None,
        effective_message=msg,
        effective_chat=chat,
        effective_user=SimpleNamespace(id=7, first_name="Mod"),
        callback_query=None,
    )


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def test_a_proof_prompt_never_renders_a_missing_target(monkeypatch: Any) -> None:
    """An empty scope must end the step, not post 'Banning 0'."""
    sends: list[str] = []

    async def _reply(*_args: Any, **_kwargs: Any) -> Any:
        sends.append("reply")
        return SimpleNamespace(id=1)

    async def _edit(*_args: Any, **_kwargs: Any) -> Any:
        sends.append("edit")
        return SimpleNamespace(id=1)

    monkeypatch.setattr(ban_rules_step, "reply_rich_result", _reply)
    monkeypatch.setattr(ban_rules_step, "safe_edit_cb", _edit)
    scope: dict[str, Any] = {}
    ctx = _ctx()
    ctx.user_data = scope

    state = asyncio.run(ban_rules_step._show_proof(ctx))

    assert state == ConversationHandler.END
    assert sends == []
    assert scope == {}


def test_a_rules_note_without_a_live_ban_passes_through() -> None:
    """The flatly registered text handler must not capture arbitrary text."""
    scope: dict[str, Any] = {}
    ctx = _ctx(text="mana gw udah rela ngebuang kegamonan gwa")
    ctx.user_data = scope

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await ban_rules_step.on_ban_rules_note(ctx)

    asyncio.run(_run())
    assert scope == {}


def test_an_abandoned_ban_picker_does_not_capture_group_text() -> None:
    """A stale ban scope needs an explicit note phase before accepting text."""
    scope: dict[str, Any] = {
        "ban_target_id": 99,
        "ban_admin_id": 7,
        "ban_prompt_msg_id": 12,
        "ban_prompt_chat_id": -100,
    }
    ctx = _ctx()
    ctx.user_data = scope

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await ban_rules_step.on_ban_rules_note(ctx)

    asyncio.run(_run())
    assert "ban_rules_note" not in scope


def test_an_unknown_command_without_an_appeal_passes_through(monkeypatch: Any) -> None:
    """'.appeal' with no live appeal must reach the next flow's fallback."""
    scope: dict[str, Any] = {}
    ctx = _ctx(text=".appeal")
    ctx.user_data = scope
    replies: list[Any] = []

    async def _reply(*args: Any, **kwargs: Any) -> Any:
        _ = kwargs
        replies.append(args)
        return None

    monkeypatch.setattr(appeal_submit, "reply_rich", _reply)

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await appeal_submit.appeal._end(ctx)

    asyncio.run(_run())
    assert replies == []
    assert scope == {}


def test_appeal_media_without_a_live_appeal_passes_through() -> None:
    """A private photo belongs to the ban proof flow, not to an idle appeal."""
    scope: dict[str, Any] = {}
    ctx = _ctx(text=None)
    ctx.user_data = scope

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await appeal_submit.appeal._on_unexpected(ctx)

    asyncio.run(_run())
    assert scope == {}


def test_a_reason_without_a_live_flow_passes_through() -> None:
    """Kick, mute, and warn text handlers must not capture stray messages."""
    flow = mod_action_steps._ModActionFlow(
        "kick",
        mod_action_steps.BuildReason("kick"),
        mod_action_steps.BuildProof("kick"),
        _noop,
        "moderator",
    )
    conv = flow.build(_noop, build_prefixed_filters("tckick"))
    _ = conv
    scope: dict[str, Any] = {}
    ctx = _ctx()
    ctx.user_data = scope

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await flow._on_reason_text(ctx)
        with pytest.raises(ContinuePropagation):
            await flow._on_rules_note_text(ctx)
        with pytest.raises(ContinuePropagation):
            await flow._on_reason_unexpected(ctx)
        with pytest.raises(ContinuePropagation):
            await flow._on_proof_unexpected(ctx)

    asyncio.run(_run())
    assert scope == {}


def test_the_proof_prompt_builder_rejects_a_zero_target() -> None:
    """Even a direct caller cannot synthesize a 'Banning 0' prompt."""
    with pytest.raises(ValueError, match="positive target"):
        proof_steps.proof_prompt_content(0, "", "reason", "en-US")


def test_a_cancelled_flush_is_awaited_before_the_scope_is_reused() -> None:
    """Old cleanup must not clear the keys of a ban started immediately after."""
    key = (-100, 7)

    async def _run() -> None:
        scope: dict[str, Any] = {"ban_target_id": 99, "ban_admin_id": 7}
        blocker = asyncio.Event()

        async def _parked() -> None:
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_parked())
        await asyncio.sleep(0)
        session = proof_session.ProofSession(
            meta=dict(scope), scope=scope, deadline=0.0, last_arrival=0.0
        )
        session.flush_task = task
        ban_session.proof_sessions.add(key, session)

        await ban_session._cancel_proof_session(scope)

        assert task.done()
        assert key not in ban_session.proof_sessions
        assert scope == {}

    asyncio.run(_run())
