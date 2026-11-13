# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick executor + conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from tcbot import database as db
from tcbot.modules.helper import guards, keyboards, messages
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_reply, send_log
from tcbot.modules.helper.pipelines.demote_flow import demote_before_enforcement
from tcbot.modules.helper.pipelines.proof_flow import (
    BuildProof,
    ProofUpload,
    upload_proof_for_action,
)
from tcbot.modules.helper.pipelines.reason_flow import BuildReason, build_modaction_conv
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Message, Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

# * Per-action BuildReason and BuildProof instances; imported by kicking.py
reason = BuildReason("kick")
proof = BuildProof("kick")


# ────────────────────────── Kick executor ───────────────────────── #


async def execute_kick(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_msgs: list[Message] | None = None,
    prompt_chat: int | None = None,
    prompt_id: int | None = None,
) -> None:
    """Kick (ban then immediately unban) a user from the current group."""
    msg = update.effective_message
    effective_user = update.effective_user
    effective_chat = update.effective_chat
    if effective_user is None or effective_chat is None or msg is None:
        log.warning("Kick executor called without user, chat, or message")
        return
    chat_id = effective_chat.id
    admin_id = effective_user.id
    admin_fname = effective_user.first_name
    locale = await locale_for_update(update)

    # * Re-check the executor against the target before anything is
    # * recorded. The entry command compared the two roles, but the proof
    # * window can stay open for a minute, and a target promoted in that
    # * window must not be actioned by a moderator who no longer outranks
    # * them. The check runs before the audit row and the proof upload so
    # * a refused kick leaves no record and no orphan proof behind.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="tester",
        action="Kick",
        locale=locale,
    )
    if refusal is not None:
        await safe_reply(
            msg,
            refusal,
            log_label="execute_kick rank-refusal",
            parse_mode=None,
        )
        return

    # * Upload proof concurrently with enforcement: the ban below must not wait
    # * for the proof-channel round trip. The task is awaited after the ban
    # * lands and before the keyboards are built; on ban failure it is
    # * cancelled so no orphan upload outlives the executor. An upload failure
    # * still degrades to no proof link, exactly as before.
    proof_task: asyncio.Task[ProofUpload] | None = None
    if proof_msgs:
        proof_task = asyncio.create_task(
            upload_proof_for_action(
                ctx.bot, proof_msgs, target_id, admin_id, admin_fname
            )
        )

    # * Audit first: the DB kick record must exist before enforcement.
    # * A failed write aborts with a retry reply instead of leaving an
    # * enforced but unaudited kick that /check can never see.
    try:
        await db.kicks_db.log_kick(target_id, chat_id, reason_text, admin_id)
    except Exception:
        log.exception("log_kick DB write failed for target=%d", target_id)
        # * The kick was never recorded, so the proof upload must not
        # * outlive it: an orphan proof in the proofs channel points at a
        # * moderation action that does not exist.
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_kick log-failed",
            parse_mode=None,
        )
        return
    # * Demote before the ban lands: a role-holding target must not keep
    # * federation rank while the ban is live. This closes the TOCTOU
    # * window the cancelable reason and proof steps opened.
    # * Best-effort by design: the audit row above already exists, so a
    # * lookup failure must not skip the enforcement.
    await demote_before_enforcement(
        ctx.bot,
        target_id,
        target_name,
        trigger="kick",
        executor_id=admin_id,
        executor_fname=admin_fname,
    )
    try:
        await asyncio.wait_for(
            ctx.bot.ban_chat_member(chat_id, target_id),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        )
        proof_link: str | None = None
        if proof_task is not None:
            try:
                proof_link = (await proof_task).link
            except asyncio.CancelledError:
                proof_task.cancel()
                raise
            except Exception:
                log.warning("Kick proof upload skipped for target=%d", target_id)
                proof_link = None
        proof_kb = keyboards.action_proof_kb(target_id, proof_link, locale)
        chat_title = effective_chat.title or str(chat_id)
        log_text = messages.kick_log(
            target_id,
            target_name,
            admin_id,
            admin_fname,
            reason_text,
            chat_id,
            chat_title,
        )
        # * Two independent side-effects run in parallel: the unban that
        # * converts the ban into a "kick" (user can rejoin) and the
        # * federation log-channel post. The audit write already landed
        # * above, so a failure here can never leave an unaudited kick.
        # * The user-facing reply runs *after* the unban completes so we
        # * know whether the unban failed -- otherwise the admin would see
        # * "kicked" while the user is still banned.
        unban_result, log_send_result = await asyncio.gather(
            ctx.bot.unban_chat_member(chat_id, target_id, only_if_banned=True),
            send_log(
                ctx.bot,
                log_text,
                reply_markup=proof_kb,
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((unban_result, log_send_result))
        if isinstance(unban_result, BaseException):
            # * One bounded retry: a transient refusal otherwise strands
            # * the user banned with only a kick log (the ban record
            # * repairs it, which a kick never records).
            log.debug(
                "unban_chat_member retrying once for target=%d: %s",
                target_id,
                unban_result,
            )
            try:
                await asyncio.wait_for(
                    ctx.bot.unban_chat_member(chat_id, target_id, only_if_banned=True),
                    timeout=TELEGRAM_LOOKUP_TIMEOUT,
                )
                log.info("kick unban retry succeeded for target=%d", target_id)
                unban_result = True
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning(
                    "unban_chat_member failed after kick for target=%d: %s",
                    target_id,
                    unban_result,
                )
        if isinstance(log_send_result, BaseException):
            log.error("Kick log send failed: %s", log_send_result)
        unban_warning = (
            Safe(t("kicking.warn.unban", locale))
            if isinstance(unban_result, BaseException)
            else Safe("")
        )
        summary = t(
            "kicking.summary.body",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            reason=reason_text,
            rejoin=Safe(t("kicking.rejoin.body", locale)),
            warning=unban_warning,
        )
        # * Edit the proof prompt in place like the mute executor: a fresh
        # * reply for every kick doubles the chat noise and buries the
        # * prompt. Falls back to a reply when the prompt is gone/unknown.
        if prompt_chat is not None and prompt_id is not None:
            try:
                await ctx.bot.edit_message_text(
                    summary,
                    chat_id=prompt_chat,
                    message_id=prompt_id,
                    parse_mode="MarkdownV2",
                    reply_markup=proof_kb,
                )
            except Exception as exc:
                log.debug("Kick summary prompt edit failed: %s", exc)
                await safe_reply(
                    msg,
                    summary,
                    log_label="Kick summary fallback",
                    reply_markup=proof_kb,
                )
        else:
            await safe_reply(msg, summary, log_label="Kick", reply_markup=proof_kb)
    except Exception:
        # * Ban failed while the proof upload may still be in flight: cancel
        # * it so no orphan upload outlives this executor.
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        log.exception("Kick failed for %s in %s", target_id, chat_id)
        await safe_reply(
            msg,
            t(
                "kicking.error.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="Kick error",
        )


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop kick data from the conversation scope and call execute_kick."""
    if ctx.user_data is None:
        log.warning("_exec_kick called without user_data")
        return
    scope = flow_scope(ctx, update)
    target_id = scope.pop("kick_target_id", 0)
    target_name = scope.pop("kick_target_name", "")
    reason_text = scope.pop(
        "kick_reason", replies.no_reason(await locale_for_update(update), plain=True)
    )
    proof_msgs = scope.pop("kick_proof_msgs", None)
    prompt_chat = scope.pop("kick_prompt_chat", None)
    prompt_id = scope.pop("kick_prompt_id", None)
    scope.pop("kick_extra_info", None)
    await execute_kick(
        update,
        ctx,
        target_id,
        target_name,
        reason_text,
        proof_msgs=proof_msgs,
        prompt_chat=prompt_chat,
        prompt_id=prompt_id,
    )


# ─────────────────── ConversationHandler factory ────────────────── #


def kick_conversation(entry_fn: Callable[..., Any], entry_filter: BaseFilter) -> object:
    """Return the kick ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason, proof, entry_fn, _exec_kick, entry_filter, min_role="tester"
    )
