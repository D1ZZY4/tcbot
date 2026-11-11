# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The moderation payload must stay scoped to one (chat, user) conversation.

python-telegram-bot stores ``ctx.user_data`` per user id, so one dict is
shared by every chat a user is in. The moderation conversations are
registered ``per_chat=True, per_user=True``, so a payload kept directly in
``ctx.user_data`` belongs to two conversations at once.

A federation admin moderating in several groups is the normal case, not an
edge case: starting a second action in another group overwrote the target,
the reason and the prompt of the first one, so the first group enforced
against the second target. These tests pin the scoping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import ban_flow
from tcbot.modules.helper.scope import clear_flow_scope, conversation_key, flow_scope


class _FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "supergroup"


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeUpdate:
    def __init__(self, chat_id: int, user_id: int) -> None:
        self.effective_chat = _FakeChat(chat_id)
        self.effective_user = _FakeUser(user_id)
        self.effective_message: Any = None
        self.callback_query = None


class _FakeCtx:
    def __init__(self) -> None:
        # * One dict per user id, exactly like PTB: the same object is
        # * handed to every chat that user is in.
        self.user_data: dict[str, Any] = {}
        self.bot = SimpleNamespace(username="testbot")


def test_the_scope_is_separate_per_chat_of_the_same_user() -> None:
    """Two chats of one moderator must not share their flow payload."""
    ctx = _FakeCtx()
    group_a = _FakeUpdate(chat_id=100, user_id=42)
    group_b = _FakeUpdate(chat_id=200, user_id=42)

    scope_a = flow_scope(ctx, group_a)  # type: ignore[arg-type]
    scope_b = flow_scope(ctx, group_b)  # type: ignore[arg-type]

    scope_a["ban_target_id"] = 111
    scope_b["ban_target_id"] = 222

    assert scope_a["ban_target_id"] == 111
    assert scope_b["ban_target_id"] == 222
    assert scope_a is not scope_b


def test_the_scope_is_shared_inside_one_chat() -> None:
    """The same conversation must see the same payload on every update."""
    ctx = _FakeCtx()
    first = _FakeUpdate(chat_id=100, user_id=42)
    second = _FakeUpdate(chat_id=100, user_id=42)

    scope = flow_scope(ctx, first)  # type: ignore[arg-type]
    scope["ban_target_id"] = 111

    assert flow_scope(ctx, second) is scope  # type: ignore[arg-type]


def test_the_scope_is_separate_per_user_of_the_same_chat() -> None:
    """Two moderators in one group must not read each other's payload."""
    ctx = _FakeCtx()
    admin_a = _FakeUpdate(chat_id=100, user_id=42)
    admin_b = _FakeUpdate(chat_id=100, user_id=43)

    scope_a = flow_scope(ctx, admin_a)  # type: ignore[arg-type]
    scope_b = flow_scope(ctx, admin_b)  # type: ignore[arg-type]

    scope_a["warn_target_id"] = 111

    assert "warn_target_id" not in scope_b


def test_clearing_one_scope_leaves_the_other_alone() -> None:
    """Ending one conversation must not tear down another one."""
    ctx = _FakeCtx()
    group_a = _FakeUpdate(chat_id=100, user_id=42)
    group_b = _FakeUpdate(chat_id=200, user_id=42)

    scope_a = flow_scope(ctx, group_a)  # type: ignore[arg-type]
    scope_b = flow_scope(ctx, group_b)  # type: ignore[arg-type]
    scope_a["ban_target_id"] = 111
    scope_b["ban_target_id"] = 222

    clear_flow_scope(ctx, group_a)  # type: ignore[arg-type]

    assert "ban_target_id" not in flow_scope(ctx, group_a)  # type: ignore[arg-type]
    assert flow_scope(ctx, group_b)["ban_target_id"] == 222  # type: ignore[arg-type]


def test_the_conversation_key_matches_the_registered_conversations() -> None:
    """The scope key must be the one PTB uses for per_chat + per_user."""
    update = _FakeUpdate(chat_id=100, user_id=42)
    assert conversation_key(update) == (100, 42)  # type: ignore[arg-type]
    assert (
        conversation_key(
            SimpleNamespace(effective_chat=None, effective_user=None)  # type: ignore[arg-type]
        )
        is None
    )


def test_the_ban_proof_session_snapshots_its_own_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proof upload must enforce against the target of its own group.

    This is the regression the scoping fixes: the moderator starts a ban in
    group A, starts another one in group B, then uploads the proof in group
    A. Without the scope the flush would ban the group B target.
    """
    registry: dict[tuple[int, int], Any] = {}
    monkeypatch.setattr(ban_flow, "_proof_sessions", registry)

    ctx = _FakeCtx()
    group_a = _FakeUpdate(chat_id=100, user_id=42)
    group_b = _FakeUpdate(chat_id=200, user_id=42)

    scope_a = flow_scope(ctx, group_a)  # type: ignore[arg-type]
    scope_a["ban_target_id"] = 111
    scope_a["ban_admin_id"] = 42

    scope_b = flow_scope(ctx, group_b)  # type: ignore[arg-type]
    scope_b["ban_target_id"] = 222
    scope_b["ban_admin_id"] = 42

    update_a = _FakeUpdate(chat_id=100, user_id=42)
    update_a.effective_message = object()
    outcome = asyncio.run(
        ban_flow.on_proof_received(update_a, ctx)  # type: ignore[arg-type]
    )

    assert outcome == ban_flow.WAITING_PROOF
    session = registry[(100, 42)]
    assert session.meta["ban_target_id"] == 111
    assert registry.get((200, 42)) is None
