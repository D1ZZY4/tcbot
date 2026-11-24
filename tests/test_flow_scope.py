# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The moderation payload must stay scoped to one (chat, user) conversation.

The application context keys ``user_data`` by chat and user, so one payload is
shared by every chat a user is in only when the context is built without a
chat. A federation admin moderating in several groups is the normal case, so
these tests build real contexts and pin the isolation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot.modules.helper.context import build_ctx, clear_state
from tcbot.modules.helper.pipelines import ban_actions
from tcbot.modules.helper.pipelines.proof_session import ProofSessionRegistry
from tcbot.modules.helper.scope import clear_flow_scope, conversation_key, flow_scope


def _ctx(chat_id: int, user_id: int, *, message: Any = None) -> Any:
    """Build an application context for one conversation."""
    chat = SimpleNamespace(id=chat_id, type="supergroup")
    user = SimpleNamespace(id=user_id, first_name="Admin")
    msg = message if message is not None else SimpleNamespace(chat=chat, from_user=user)
    return asyncio.run(
        build_ctx(
            cast("Any", SimpleNamespace()),
            message=cast("Any", msg),
        )
    )


def test_the_scope_is_separate_per_chat_of_the_same_user() -> None:
    """Two chats of one moderator must not share their flow payload."""
    scope_a = flow_scope(_ctx(100, 42))
    scope_b = flow_scope(_ctx(200, 42))

    scope_a["ban_target_id"] = 111
    scope_b["ban_target_id"] = 222

    assert scope_a["ban_target_id"] == 111
    assert scope_b["ban_target_id"] == 222
    assert scope_a is not scope_b


def test_the_scope_is_shared_inside_one_chat() -> None:
    """The same conversation must see the same payload on every update."""
    scope = flow_scope(_ctx(100, 42))
    scope["ban_target_id"] = 111

    assert flow_scope(_ctx(100, 42))["ban_target_id"] == 111


def test_the_scope_is_separate_per_user_of_the_same_chat() -> None:
    """Two moderators in one group must not read each other's payload."""
    scope_a = flow_scope(_ctx(100, 42))
    scope_b = flow_scope(_ctx(100, 43))

    scope_a["warn_target_id"] = 111

    assert "warn_target_id" not in scope_b


def test_clearing_one_scope_leaves_the_other_alone() -> None:
    """Ending one conversation must not tear down another one."""
    ctx_a = _ctx(100, 42)
    ctx_b = _ctx(200, 42)
    scope_a = flow_scope(ctx_a)
    scope_b = flow_scope(ctx_b)
    scope_a["ban_target_id"] = 111
    scope_b["ban_target_id"] = 222

    clear_flow_scope(ctx_a)

    assert "ban_target_id" not in flow_scope(ctx_a)
    assert flow_scope(ctx_b)["ban_target_id"] == 222


def test_an_emptied_scope_entry_is_dropped() -> None:
    """A finished conversation must leave no stale payload keys behind."""
    ctx = _ctx(100, 42)
    scope = flow_scope(ctx)
    scope["ban_target_id"] = 111

    clear_flow_scope(ctx, keys=["ban_target_id"])

    assert scope == {}


def test_a_partial_clear_keeps_the_other_payload() -> None:
    """Clearing one action leaves the payload of another action in place."""
    ctx = _ctx(100, 42)
    scope = flow_scope(ctx)
    scope["ban_target_id"] = 111
    scope["warn_target_id"] = 222

    clear_flow_scope(ctx, keys=["ban_target_id"])

    kept = flow_scope(ctx)
    assert "ban_target_id" not in kept
    assert kept["warn_target_id"] == 222


def test_the_conversation_key_matches_the_registered_conversations() -> None:
    """The conversation key must be (chat id, user id)."""
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=100),
        effective_user=SimpleNamespace(id=42),
    )
    assert conversation_key(update) == (100, 42)
    assert (
        conversation_key(SimpleNamespace(effective_chat=None, effective_user=None))
        is None
    )


def test_the_ban_proof_session_snapshots_its_own_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proof upload must enforce against the target of its own group."""
    registry = ProofSessionRegistry()
    monkeypatch.setattr(ban_actions, "proof_sessions", registry)

    ctx_a = _ctx(100, 42)
    ctx_b = _ctx(200, 42)
    scope_a = flow_scope(ctx_a)
    scope_a["ban_target_id"] = 111
    scope_a["ban_admin_id"] = 42
    scope_b = flow_scope(ctx_b)
    scope_b["ban_target_id"] = 222
    scope_b["ban_admin_id"] = 42

    async def _scenario() -> int:
        outcome = await ban_actions.on_proof_received(ctx_a)
        session = registry[(100, 42)]
        assert session.meta["ban_target_id"] == 111
        assert registry.get((200, 42)) is None
        if session.flush_task is not None:
            session.flush_task.cancel()
            await asyncio.gather(session.flush_task, return_exceptions=True)
        return outcome

    assert asyncio.run(_scenario()) == ban_actions.WAITING_PROOF
    asyncio.run(clear_state(100, 42))
    asyncio.run(clear_state(200, 42))
