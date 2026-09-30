# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban proof-collection conversation handlers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import clear_markup_cb, safe_edit_cb, safe_reply

# * Registry and executor resolve through the package namespace, keeping one
# * live binding for every submodule and caller.
from tcbot.modules.helper.workflows import ban_flow as _flow
from tcbot.modules.helper.workflows.ban_flow.session import (
    _cancel_proof_session,
    _clear_ban_state,
    _ProofSession,
)
from tcbot.modules.helper.workflows.ban_flow.shared import (
    BAN_USER_DATA_KEYS,
    WAITING_PROOF,
    proof,
)
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    from telegram import Bot, InlineKeyboardMarkup

log = get_logger(__name__)


async def demote_ban_target(
    msg: Message,
    bot: Bot,
    target_id: int,
    target_fname: str,
    target_role: str | None,
    admin_id: int,
    admin_fname: str,
) -> bool:
    """Auto-demote a role-holding ban target; reply and abort on failure.

    Shared by the entry fresh-ban path and the update-confirm Continue
    handler so demotion always lands after the final confirmation. Returns
    True when the caller may proceed.
    """
    if not target_role:
        return True
    return await Demote.auto_demote_or_abort(
        msg,
        bot,
        target_id,
        target_fname,
        target_role,
        admin_id,
        admin_fname,
        trigger="ban",
    )


def proof_prompt_content(
    target_id: int, target_fname: str, reason: str, locale: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Build the proof-collection prompt text and keyboard (single owner).

    Used by the entry fresh-ban path (as a reply) and the update-confirm
    Continue handler (as an in-place edit of the confirm message).
    """
    return (
        proof.noted_prompt(
            "ban", reason, user_ref(target_id, target_fname), locale=locale
        ),
        proof.keyboard(locale),
    )


async def on_ban_update_continue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Proceed from the re-ban confirmation to proof collection."""
    q = update.callback_query
    msg = update.effective_message
    if q is None or msg is None or ctx.user_data is None:
        return ConversationHandler.END
    if not isinstance(msg, Message):
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    await q.answer()
    # * Re-check the tapper rank: the confirm card can outlive a demotion.
    tapper = update.effective_user
    if tapper is None or not await decorators.recheck_executor_rank(
        msg, tapper.id, min_role="developer"
    ):
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    # * Entry-point authorization covers this tap like every other flow
    # * callback: the tapping admin passed resolve_and_check moments ago,
    # * and demotion below still runs before anything enforces.
    target_id = int(ctx.user_data.get("ban_target_id", 0) or 0)
    target_fname = str(ctx.user_data.get("ban_target_fname") or target_id)
    reason = str(ctx.user_data.get("ban_reason") or "")
    admin_id = int(ctx.user_data.get("ban_admin_id", 0) or 0)
    admin_fname = str(ctx.user_data.get("ban_admin_fname") or "Admin")
    target_role = ctx.user_data.get("ban_target_role")
    if not target_id or not reason:
        # * Keys cleared under us (e.g. a timeout raced the tap):
        # * nothing actionable to continue with.
        return ConversationHandler.END
    if not await demote_ban_target(
        msg,
        ctx.bot,
        target_id,
        target_fname,
        target_role if isinstance(target_role, str) else None,
        admin_id,
        admin_fname,
    ):
        return ConversationHandler.END
    text, kb = proof_prompt_content(
        target_id, target_fname, reason, await locale_for_update(update)
    )
    try:
        await q.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception as exc:
        log.debug("Ban continue prompt edit failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF


async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Buffer proof media into the live session; flush on Done or silence."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if msg is None or chat is None or user is None:
        return WAITING_PROOF
    if ctx.user_data is None:
        return ConversationHandler.END
    if not ctx.user_data.get("ban_target_id"):
        # * Post-flush zombie: the background flush already executed the
        # * ban and cleared the ban keys, but the conversation is still
        # * open. End silently instead of opening an orphan session whose
        # * meta could never execute.
        return ConversationHandler.END

    key = (chat.id, user.id)
    session = _flow._proof_sessions.get(key)
    if session is not None and session.flushing:
        # * A flush already claimed this session (Done tap or silence
        # * window won the race): first submission wins, drop the rest.
        return ConversationHandler.END
    if session is None:
        ctx.user_data["ban_executing"] = True
        now = monotonic()
        session = _ProofSession(
            meta=dict(ctx.user_data),
            user_data=ctx.user_data,
            deadline=now + _flow._PROOF_COLLECT_MAX_S,
            last_arrival=now,
        )
        _flow._proof_sessions[key] = session
        task = asyncio.create_task(_flow._flush_session(key, ctx.bot))
        session.flush_task = task
    else:
        session.last_arrival = monotonic()
    session.msgs.append(msg)
    return WAITING_PROOF


async def on_done_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Flush collected proof immediately when the moderator taps Done."""
    q = update.callback_query
    if q is None or ctx.user_data is None:
        return ConversationHandler.END
    chat = update.effective_chat
    user = update.effective_user
    key = (chat.id, user.id) if chat is not None and user is not None else None
    if key is None:
        return ConversationHandler.END
    session = _flow._proof_sessions.get(key)
    if session is None or session.flushing or not session.msgs:
        if not ctx.user_data.get("ban_target_id"):
            # * Post-flush zombie tap: the ban already executed, so there
            # * is nothing to nudge for. Answer the spinner and end.
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Ban done-proof zombie answer failed: %s", exc)
            return ConversationHandler.END
        # * Nothing to flush (or the auto-flush already claimed it):
        # * nudge instead of executing an empty proof.
        try:
            locale = await locale_for_update(update)
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
    # * Synchronous claim without popping: the session stays visible with
    # * flushing set, so arrivals during execution still drop via the
    # * flushing check in on_proof_received instead of double-executing.
    session.flushing = True
    if session.flush_task is not None:
        session.flush_task.cancel()
    try:
        await q.answer()
    except Exception as exc:
        log.debug("Ban done-proof answer failed: %s", exc)
    if not session.meta.get("ban_target_id") or not session.meta.get("ban_admin_id"):
        log.warning("Done-proof flush aborted: meta missing target_id or admin_id")
        _flow._proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    # * Rank re-check: a moderator demoted during proof collection must not
    # * enforce from a stale prompt.
    tap_msg = update.effective_message
    if user is None or not isinstance(tap_msg, Message):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _flow._proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    if not await decorators.recheck_executor_rank(
        tap_msg, user.id, min_role="developer"
    ):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _flow._proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    try:
        await _flow._execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof _execute_ban raised")
    finally:
        # * Same-object guard: the flush task we cancelled (and any earlier
        # * code) must not wipe a successor session that took over the same
        # * (chat, user) key during the cancellation-unwind window.
        if _flow._proof_sessions.get(key) is session:
            _flow._proof_sessions.pop(key, None)
            _clear_ban_state(session.user_data)
    return ConversationHandler.END


async def on_proof_unexpected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unexpected message types during proof collection."""
    if ctx.user_data is not None and not ctx.user_data.get("ban_target_id"):
        # * Post-flush zombie: the ban already executed and the prompt
        # * already shows the summary. End silently instead of nagging
        # * every later message for proof that is no longer needed.
        return ConversationHandler.END
    if update.effective_message:
        await safe_reply(
            update.effective_message,
            t(
                "banning.state.proof_expected",
                await locale_for_update(update),
                plain=True,
            ),
            log_label="Ban proof-unexpected",
            parse_mode=None,
        )
    return WAITING_PROOF


async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Acknowledge the cancel button and end the proof-collection conversation."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()

    _cancel_proof_session(ctx.user_data)

    # * Edit the prompt in place instead of a new reply, and strip its
    # * buttons: a text-only edit keeps the old keyboard, which would leave
    # * dead Cancel/Done buttons behind on an ended conversation.
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(update), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Notify the user that the proof window expired and end the conversation."""
    had_state = bool((ctx.user_data or {}).get("ban_target_id"))
    prompt_chat: int | None = None
    prompt_msg_id: int | None = None
    if ctx.user_data is not None:
        raw_chat = ctx.user_data.get("ban_prompt_chat_id")
        raw_msg = ctx.user_data.get("ban_prompt_msg_id")
        prompt_chat = raw_chat if isinstance(raw_chat, int) else None
        prompt_msg_id = raw_msg if isinstance(raw_msg, int) else None
    _cancel_proof_session(ctx.user_data)

    # * Strip the stale prompt's buttons so a late Cancel/Done tap does not
    # * spin forever on an ended conversation; the timeout notice below
    # * answers the triggering command itself.
    if prompt_chat and prompt_msg_id:
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=prompt_chat, message_id=prompt_msg_id
            )
        except Exception as exc:
            log.debug("Ban proof-timeout markup clear failed: %s", exc)
    if not had_state:
        # * Post-flush zombie: the ban already executed, so the timeout
        # * text would falsely claim no ban was issued. End silently.
        return ConversationHandler.END
    if update.effective_message:
        await safe_reply(
            update.effective_message,
            t(
                "banning.state.timeout",
                await locale_for_update(update),
                plain=True,
            ),
            log_label="Ban proof-timeout",
            parse_mode=None,
        )
    return ConversationHandler.END
