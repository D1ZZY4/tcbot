# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for reason_flow: pure helpers, BuildReason, and build_modaction_conv closures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    BuildReason,
    build_modaction_conv,
    parse_inline_reason,
)

# ─────────────────────────── Helpers ────────────────────────────── #


def _conv(
    action: str = "ban",
    skip_reason: bool = True,
    skip_proof: bool = True,
) -> tuple[object, AsyncMock]:
    """Build a ConversationHandler and return (conv, executor_mock)."""
    reason = BuildReason(action, skip_allowed=skip_reason)
    proof = BuildProof(action, skip_allowed=skip_proof)
    executor = AsyncMock()
    conv = build_modaction_conv(
        reason,
        proof,
        entry_fn=AsyncMock(),
        executor=executor,
        entry_filter=Mock(),
    )
    return conv, executor


def _ctx(user_data: dict | None = None, bot=None) -> SimpleNamespace:
    return SimpleNamespace(
        user_data=user_data if user_data is not None else {},
        bot=bot
        or SimpleNamespace(
            edit_message_text=AsyncMock(),
        ),
    )


# ─────────────────────── parse_inline_reason ────────────────────── #


def test_parse_inline_reason_with_explicit_target() -> None:
    """When the first arg is the target, reason is built from args[1:]."""
    assert (
        parse_inline_reason(["@user", "spam", "flood"], has_explicit_target=True)
        == "spam flood"
    )


def test_parse_inline_reason_without_explicit_target() -> None:
    """Without an explicit target all tokens join as the reason."""
    assert (
        parse_inline_reason(["spam", "flood"], has_explicit_target=False)
        == "spam flood"
    )


def test_parse_inline_reason_empty_returns_blank() -> None:
    assert parse_inline_reason([], has_explicit_target=False) == ""
    assert parse_inline_reason(["@user"], has_explicit_target=True) == ""


# ─────────────────────── BuildReason.keyboard ───────────────────── #


def test_build_reason_keyboard_with_skip_has_two_buttons() -> None:
    br = BuildReason("ban", skip_allowed=True)
    kb = br.keyboard()
    buttons = kb.inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert "Skip" in labels
    assert "Cancel" in labels
    assert len(buttons) == 2


def test_build_reason_keyboard_without_skip_has_one_button() -> None:
    br = BuildReason("ban", skip_allowed=False)
    kb = br.keyboard()
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 1
    assert buttons[0].text == "Cancel"


# ─────────────────────── BuildReason.prompt ─────────────────────── #


def test_build_reason_prompt_includes_skip_hint_when_allowed() -> None:
    br = BuildReason("ban", skip_allowed=True, skip_label="Skip")
    p = br.prompt("@Target", "ban")
    assert "Skip" in p
    assert "ban" in p.lower()


def test_build_reason_prompt_omits_skip_hint_when_not_allowed() -> None:
    br = BuildReason("ban", skip_allowed=False)
    p = br.prompt("@Target", "ban")
    assert "Skip" not in p


def test_build_reason_prompt_appends_extra_info() -> None:
    br = BuildReason("warn", skip_allowed=False)
    p = br.prompt("@Target", "warn", extra_info="(3 prior offences)")
    assert "(3 prior offences)" in p


# ────────────── build_modaction_conv: WAITING_REASON handlers ───── #


async def test_on_reason_text_stores_reason_and_advances_to_proof() -> None:
    """Typing a reason saves it in user_data and transitions to WAITING_PROOF."""
    conv, _ = _conv(action="warn", skip_reason=True)
    on_reason_text = conv.states[WAITING_REASON][0].callback

    msg = SimpleNamespace(
        text="spam",
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=10)),
    )
    update = SimpleNamespace(effective_message=msg)
    user_data: dict = {"warn_target_name": "Target"}
    ctx = _ctx(user_data=user_data)

    result = await on_reason_text(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == WAITING_PROOF
    assert user_data["warn_reason"] == "spam"
    msg.reply_text.assert_awaited_once()


async def test_on_reason_text_edits_existing_prompt_when_ids_set() -> None:
    """When prompt_id and prompt_chat are in user_data the bot edits instead of replying."""
    conv, _ = _conv(action="warn", skip_reason=True)
    on_reason_text = conv.states[WAITING_REASON][0].callback

    edit_mock = AsyncMock()
    bot = SimpleNamespace(edit_message_text=edit_mock)
    msg = SimpleNamespace(text="flood", reply_text=AsyncMock())
    update = SimpleNamespace(effective_message=msg)
    user_data = {
        "warn_target_name": "Target",
        "warn_prompt_chat": -100,
        "warn_prompt_id": 55,
    }
    ctx = _ctx(user_data=user_data, bot=bot)

    result = await on_reason_text(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == WAITING_PROOF
    edit_mock.assert_awaited_once()
    msg.reply_text.assert_not_awaited()


async def test_on_skip_reason_sets_default_and_advances() -> None:
    """Tapping Skip sets 'No reason provided' and transitions to WAITING_PROOF."""
    conv, _ = _conv(action="ban", skip_reason=True)
    # With skip_allowed=True: state is [text, skip, cancel]
    on_skip_reason = conv.states[WAITING_REASON][1].callback

    q = SimpleNamespace(
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)
    user_data: dict = {"ban_target_name": "Target"}
    ctx = _ctx(user_data=user_data)

    result = await on_skip_reason(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == WAITING_PROOF
    assert user_data["ban_reason"] == "No reason provided"
    q.answer.assert_awaited_once()
    q.edit_message_text.assert_awaited_once()


# ────────────── build_modaction_conv: WAITING_PROOF handlers ────── #


async def test_on_proof_records_desc_and_calls_executor() -> None:
    """A photo message is recorded and the executor fires; conversation ends."""
    conv, executor = _conv(action="ban")
    on_proof = conv.states[WAITING_PROOF][0].callback

    msg = SimpleNamespace(
        message_id=7,
        photo=[SimpleNamespace(file_id="fid")],
        video=None,
    )
    update = SimpleNamespace(effective_message=msg)
    ctx = _ctx(user_data={})

    result = await on_proof(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    assert result == ConversationHandler.END
    assert ctx.user_data.get("ban_proof_desc") == "Photo (msg 7)"
    executor.assert_awaited_once()


async def test_on_proof_no_media_does_not_set_desc() -> None:
    """A message with no photo/video leaves proof_desc unset but still fires executor."""
    conv, executor = _conv(action="ban")
    on_proof = conv.states[WAITING_PROOF][0].callback

    msg = SimpleNamespace(message_id=9, photo=None, video=None)
    update = SimpleNamespace(effective_message=msg)
    ctx = _ctx(user_data={})

    result = await on_proof(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    assert result == ConversationHandler.END
    assert "ban_proof_desc" not in ctx.user_data
    executor.assert_awaited_once()


async def test_on_skip_proof_calls_executor_and_ends() -> None:
    """Tapping Skip Proof calls executor without setting proof_desc."""
    conv, executor = _conv(action="ban")
    on_skip_proof = conv.states[WAITING_PROOF][1].callback

    q = SimpleNamespace(answer=AsyncMock())
    update = SimpleNamespace(callback_query=q)
    ctx = _ctx(user_data={})

    result = await on_skip_proof(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )

    assert result == ConversationHandler.END
    q.answer.assert_awaited_once()
    executor.assert_awaited_once()


# ──────────────── build_modaction_conv: cancel / fallback ───────── #


async def test_on_cancel_answers_edits_and_ends() -> None:
    """Cancel callback ends the conversation immediately."""
    conv, _ = _conv(action="ban")
    # Cancel handler is in fallbacks[0]
    on_cancel = conv.fallbacks[0].callback

    q = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=q)
    ctx = _ctx()

    result = await on_cancel(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    assert result == ConversationHandler.END
    q.answer.assert_awaited_once()
    q.edit_message_text.assert_awaited_once()
    assert "cancelled" in q.edit_message_text.await_args.args[0].lower()


async def test_end_conv_replies_and_ends() -> None:
    """The fallback command handler replies and ends the conversation."""
    conv, _ = _conv(action="ban")
    end_conv = conv.fallbacks[1].callback

    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_message=msg)
    ctx = _ctx()

    result = await end_conv(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    assert result == ConversationHandler.END
    msg.reply_text.assert_awaited_once()
    assert "cancelled" in msg.reply_text.await_args.args[0].lower()
