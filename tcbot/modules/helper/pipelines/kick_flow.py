# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick executor + conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, guards, messages
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    replies,
    reply_rich,
    safe_edit_message,
    send_log,
)
from tcbot.modules.helper.pipelines.demote_flow import demote_before_enforcement
from tcbot.modules.helper.pipelines.proof_flow import (
    BuildProof,
    ProofUpload,
    upload_proof_for_action,
)
from tcbot.modules.helper.pipelines.reason_flow import (
    BuildReason,
    build_modaction_conv,
    rules_from_scope,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import is_benign_telegram_error, throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Message, Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

# * Per-action BuildReason and BuildProof instances; imported by kick.py
reason = BuildReason("kick", skip_allowed=False)
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
        min_role="moderator",
        action="Kick",
        locale=locale,
    )
    if refusal is not None:
        await reply_rich(
            msg,
            refusal,
            log_label="execute_kick rank-refusal",
            parse_mode=None,
        )
        return

    # * Optional proof is archived with the decision, so it has to land
    # * before the audit row. The upload starts here and is awaited once;
    # * a failed upload degrades to a kick without evidence.
    proof_task: asyncio.Task[ProofUpload] | None = None
    if proof_msgs:
        proof_task = asyncio.create_task(
            upload_proof_for_action(
                ctx.bot, proof_msgs, target_id, admin_id, admin_fname
            )
        )
    proof_upload: ProofUpload | None = None
    if proof_task is not None:
        try:
            proof_upload = await proof_task
        except asyncio.CancelledError:
            proof_task.cancel()
            raise
        except Exception:
            log.warning("Kick proof upload skipped for target=%d", target_id)

    # * The proof upload can outlive a demotion or a target promotion.
    # * Repeat the fresh gate immediately before the audit record.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="moderator",
        action="Kick",
        locale=locale,
    )
    if refusal is not None:
        await reply_rich(
            msg,
            refusal,
            log_label="execute_kick rank-refusal after proof",
            parse_mode=None,
        )
        return

    # * Audit first: the DB kick record must exist before enforcement.
    # * A failed write aborts with a retry reply instead of leaving an
    # * enforced but unaudited kick that /check can never see.
    kick_action_id: int | None = None
    kick_delivered = False
    rule_ids, rule_note = rules_from_scope(flow_scope(ctx, update), "kick")
    try:
        kick_action_id = await db.kicks_db.log_kick(
            target_id,
            chat_id,
            reason_text,
            admin_id,
            proof_items=proof_upload.documents() if proof_upload else None,
            proof_expected_count=(
                proof_upload.expected_item_count if proof_upload else 0
            ),
            destination_chat_id=cfg.proofs[0],
            destination_thread_id=cfg.proofs[1],
            rule_item_ids=rule_ids,
            rule_selection_note=rule_note,
        )
    except Exception:
        log.exception("log_kick DB write failed for target=%d", target_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_kick log-failed",
            parse_mode=None,
        )
        return
    try:
        # * The demote belongs inside the protected block: the audit row now
        # * exists, so cancellation here must still mark it failed instead of
        # * leaving a completed kick with no enforcement and no repair.
        # * Best-effort by design: a lookup failure must not skip enforcement.
        await demote_before_enforcement(
            ctx.bot,
            target_id,
            target_name,
            trigger="kick",
            executor_id=admin_id,
            executor_fname=admin_fname,
        )
        await asyncio.wait_for(
            ctx.bot.ban_chat_member(chat_id, target_id),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        )
        proof_link: str | None = proof_upload.link if proof_upload else None
        proof_btn = buttons.action_proof_btn(target_id, proof_link, locale)
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
                reply_markup=proof_btn,
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
                if kick_action_id and not is_benign_telegram_error(unban_result):
                    # * The record started completed when the ban landed, but
                    # * the rejoin step did not. Mark it failed before the
                    # * repair queue so history never claims a finished kick
                    # * while the target is still banned.
                    try:
                        await db.kicks_db.mark_kick_failed(kick_action_id)
                    except Exception:
                        log.exception(
                            "Kick status update failed for action=%s",
                            kick_action_id,
                        )
                    # * A kick is a ban followed by an unban. If the second
                    # * step still fails, the user is banned with no active
                    # * ban record to repair from. The reconcile run keeps
                    # * the one chat as durable work and retries it.
                    try:
                        repair_run = await db.enforcement_db.queue_kick_unban_repair(
                            kick_action_id, chat_id, admin_id
                        )
                    except Exception:
                        log.exception(
                            "Kick repair queue failed for action=%s",
                            kick_action_id,
                        )
                    else:
                        if repair_run is not None:
                            log.warning(
                                "Kick left target=%d banned in %d; repair run %s queued",
                                target_id,
                                chat_id,
                                repair_run,
                            )
        kick_delivered = not isinstance(unban_result, BaseException)
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
                await safe_edit_message(
                    ctx.bot, prompt_chat, prompt_id, summary, reply_markup=proof_btn
                )
            except Exception as exc:
                log.debug("Kick summary prompt edit failed: %s", exc)
                await reply_rich(
                    msg,
                    summary,
                    log_label="Kick summary fallback",
                    reply_markup=proof_btn,
                )
        else:
            await reply_rich(msg, summary, log_label="Kick", reply_markup=proof_btn)
    except asyncio.CancelledError:
        # * Cancellation is a BaseException, so the Exception branch below
        # * would skip the repair and leave a completed kick record with no
        # * enforcement and no reconcile run. Repair it, then re-raise so
        # * shutdown cancellation still propagates.
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        if kick_action_id is not None and not kick_delivered:
            try:
                await db.kicks_db.mark_kick_failed(kick_action_id)
            except Exception:
                log.exception(
                    "Kick status update failed during cancellation for action=%s",
                    kick_action_id,
                )
        raise
    except Exception:
        # * Ban failed while the proof upload may still be in flight: cancel
        # * it so no orphan upload outlives this executor.
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        log.exception("Kick failed for %s in %s", target_id, chat_id)
        if kick_action_id is not None and not kick_delivered:
            try:
                await db.kicks_db.mark_kick_failed(kick_action_id)
            except Exception:
                log.exception("Kick status update failed for action=%s", kick_action_id)
        await reply_rich(
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
        reason,
        proof,
        entry_fn,
        _exec_kick,
        entry_filter,
        min_role="moderator",
        rules_enabled=True,
    )
