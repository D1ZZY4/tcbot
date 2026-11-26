# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban proof-collection conversation handlers."""

from __future__ import annotations

import asyncio

from pyrogram import ContinuePropagation
from pyrogram.types import Message

from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.guards import recheck_executor_rank
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import clear_markup_cb, reply_rich, safe_edit_cb
from tcbot.modules.helper.pipelines.ban_confirmation import stale_ban_callback
from tcbot.modules.helper.pipelines.ban_executor import execute_ban
from tcbot.modules.helper.pipelines.ban_session import (
    _PROOF_COLLECT_MAX_S,
    WAITING_PROOF,
    ProofSession,
    _cancel_proof_session,
    _clear_ban_state,
    _flush_session,
    proof_sessions,
)
from tcbot.modules.helper.rich.edit_msg import clear_markup
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

log = get_logger(__name__)

# ─────────────────────── Proof collection handlers ───────────────── #


async def on_proof_received(ctx: Ctx) -> int:
    """Buffer proof media into the live session; flush on Done or silence."""
    msg = ctx.effective_message
    chat = ctx.effective_chat
    user = ctx.effective_user
    if msg is None or chat is None or user is None:
        return WAITING_PROOF
    if ctx.user_data is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    if not scope.get("ban_target_id"):
        return ConversationHandler.END
    key = (chat_id_of(chat), user.id)
    session = proof_sessions.get(key)
    if session is not None and session.flushing:
        return ConversationHandler.END
    if session is None:
        now = monotonic()
        session = ProofSession(
            # * The snapshot carries this conversation's payload only, so a
            # * second action in another group cannot change the target the
            # * flush enforces against.
            meta=dict(scope),
            scope=scope,
            deadline=now + _PROOF_COLLECT_MAX_S,
            last_arrival=now,
        )
        proof_sessions.add(key, session)
        task = asyncio.create_task(_flush_session(key, ctx.bot))
        session.flush_task = task
    else:
        session.last_arrival = monotonic()
    session.msgs.append(msg)
    return WAITING_PROOF


async def on_done_proof(ctx: Ctx) -> int | None:
    """Flush collected proof immediately when the moderator taps Done."""
    q = ctx.callback_query
    if q is None or ctx.user_data is None:
        return ConversationHandler.END
    if await stale_ban_callback(ctx):
        return None
    chat = ctx.effective_chat
    user = ctx.effective_user
    key = (chat_id_of(chat), user.id) if chat is not None and user is not None else None
    if key is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    session = proof_sessions.get(key)
    if session is None or session.flushing or not session.msgs:
        if not scope.get("ban_target_id"):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Ban done-proof zombie answer failed: %s", exc)
            return ConversationHandler.END
        try:
            locale = await locale_for_update(ctx)
            await q.answer(
                t(
                    "banning.state.empty",
                    locale,
                    done=t("button.done", locale, plain=True),
                    plain=True,
                ),
                show_alert=True,
            )
        except Exception as exc:
            log.debug("Ban done-proof empty answer failed: %s", exc)
        return WAITING_PROOF
    session.flushing = True
    if session.flush_task is not None:
        session.flush_task.cancel()
        # * Await the cancelled timer before the execution path continues.
        # * Its finally clause may pop the registry entry; the cleanup below
        # * must still clear this session's scope even when that happened.
        await asyncio.gather(session.flush_task, return_exceptions=True)
    try:
        await q.answer()
    except Exception as exc:
        log.debug("Ban done-proof answer failed: %s", exc)
    if not session.meta.get("ban_target_id") or not session.meta.get("ban_admin_id"):
        log.warning("Done-proof flush aborted: meta missing target_id or admin_id")
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    tap_msg = ctx.effective_message
    if user is None or not isinstance(tap_msg, Message):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    if not await recheck_executor_rank(tap_msg, user.id, min_role="developer"):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    try:
        await execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof execute_ban raised")
    finally:
        # * Always clear this conversation's payload. The cancelled timer may
        # * already have removed the registry entry, but the scope still
        # * belongs to the session that this handler just consumed. A
        # * successor session registered meanwhile keeps its own entry.
        if proof_sessions.get(key) is session:
            proof_sessions.pop(key, session)
        _clear_ban_state(session.scope)
    return ConversationHandler.END


async def on_proof_unexpected(ctx: Ctx) -> int:
    """Reject unexpected message types during proof collection."""
    if ctx.user_data is not None and not flow_scope(ctx).get("ban_target_id"):
        # * This handler is flattened into the shared group-0 list. Without an
        # * active ban it must not consume a message another module's flow owns.
        raise ContinuePropagation()
    if ctx.effective_message:
        await reply_rich(
            ctx.effective_message,
            t(
                "banning.state.proof_expected",
                await locale_for_update(ctx),
                plain=True,
            ),
            log_label="Ban proof-unexpected",
            parse_mode=None,
        )
    return WAITING_PROOF


async def on_cancel_proof(ctx: Ctx) -> int | None:
    """Acknowledge the cancel button and end the proof-collection conversation."""
    q = ctx.callback_query
    if q is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    if await stale_ban_callback(ctx):
        return None
    # * Once flushing has started the ban is executing; cancelling mid-
    # * execute_ban would cancel the in-flight fan-out (partial ban, DB
    # * written, no summary). Ignore the tap and let execution finish.
    for sess in proof_sessions.values():
        if sess.scope is scope and sess.flushing:
            await q.answer()
            return ConversationHandler.END
    await q.answer()
    await _cancel_proof_session(scope)
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(ctx), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(ctx: Ctx) -> int:
    """Notify the user that the proof window expired."""
    scope = flow_scope(ctx)
    had_state = bool(scope.get("ban_target_id"))
    prompt_chat: int | None = None
    prompt_msg_id: int | None = None
    raw_chat = scope.get("ban_prompt_chat_id")
    raw_msg = scope.get("ban_prompt_msg_id")
    prompt_chat = raw_chat if isinstance(raw_chat, int) else None
    prompt_msg_id = raw_msg if isinstance(raw_msg, int) else None
    # * Once flushing has started the ban is executing. The timeout is the
    # * conversation fallback, so it fires for any prefixed command the
    # * moderator sends during the window. Cancelling here would cancel the
    # * in-flight fan-out after the ban record and the federation log were
    # * written: the federation would carry a ban no group enforces. The
    # * running flush owns the prompt and replaces it with its summary.
    for sess in proof_sessions.values():
        if sess.scope is scope and sess.flushing:
            log.info("Ban proof timeout ignored: the ban is already executing.")
            return ConversationHandler.END
    await _cancel_proof_session(scope)
    if prompt_chat and prompt_msg_id:
        await clear_markup(ctx.bot, prompt_chat, prompt_msg_id)
    if not had_state:
        return ConversationHandler.END
    if ctx.effective_message:
        await reply_rich(
            ctx.effective_message,
            t(
                "banning.state.timeout",
                await locale_for_update(ctx),
                plain=True,
            ),
            log_label="Ban proof-timeout",
            parse_mode=None,
        )
    return ConversationHandler.END


__all__ = [
    "on_cancel_proof",
    "on_done_proof",
    "on_proof_received",
    "on_proof_timeout",
    "on_proof_unexpected",
]
