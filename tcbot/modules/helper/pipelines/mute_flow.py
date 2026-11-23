# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute/unmute executor + conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import Bot, ChatPermissions, Update

from tcbot import cfg, enforcement_worker
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
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.i18n import Safe, bold, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_duration, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

reason = BuildReason("mute", skip_allowed=False)
proof = BuildProof("mute")

# ────────────────────────── Mute executor ───────────────────────── #


async def _execute_mute(bot: Bot, update: Update, meta: dict[str, Any]) -> None:
    """Apply a federation-wide mute across all connected groups."""
    target_id = meta.get("mute_target_id")
    admin_id = meta.get("mute_admin_id")
    if not target_id or not admin_id:
        log.warning("_execute_mute called with incomplete mute state; aborting")
        return
    target_fname = meta.get("mute_target_fname") or str(target_id)
    locale = await locale_for_update(update)
    reason_text = meta.get("mute_reason") or replies.no_reason(locale, plain=True)
    duration: timedelta | None = meta.get("mute_duration")
    proof_msgs = meta.get("mute_proof_msgs")
    prompt_chat = meta.get("mute_prompt_chat")
    prompt_id = meta.get("mute_prompt_id")
    dur_str = fmt_duration(duration, locale)
    until = utc_now() + duration if duration else None
    perms = ChatPermissions(can_send_messages=False)
    admin_fname = meta.get("mute_admin_fname", "Admin")
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        log.warning("_execute_mute called without effective_chat")
        return
    # * Re-check the executor against the target before anything is
    # * recorded. The entry command compared the two roles, but the proof
    # * window can stay open for a minute, and a target promoted in that
    # * window must not be actioned by a moderator who no longer outranks
    # * them. The check runs before the active-mute record so a refused
    # * mute leaves no state behind.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="moderator",
        action="Mute",
        locale=locale,
    )
    if refusal is not None:
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            refusal,
            parse_mode=None,
            log_level="debug",
            log_label="_execute_mute rank-refusal",
            catch_all=True,
        )
        return
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("_execute_mute: active_groups failed for target=%d", target_id)
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "muting.note.groups_fail",
                locale,
                user=Safe(user_ref(target_id, target_fname)),
            ),
            log_level="debug",
            log_label="_execute_mute groups-fail",
            catch_all=True,
        )
        return
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    proof_task: asyncio.Task[ProofUpload] | None = None
    if proof_msgs:
        proof_task = asyncio.create_task(
            upload_proof_for_action(bot, proof_msgs, target_id, admin_id, admin_fname)
        )
    proof_upload: ProofUpload | None = None
    if proof_task is not None:
        try:
            proof_upload = await proof_task
        except asyncio.CancelledError:
            proof_task.cancel()
            raise
        except Exception:
            log.warning("Mute proof upload skipped for target=%d", target_id)
    # * The proof upload can outlive a demotion or a target promotion.
    # * Repeat the fresh gate immediately before the decision is written.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="moderator",
        action="Mute",
        locale=locale,
    )
    if refusal is not None:
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            refusal,
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="_execute_mute rank-refusal after proof",
            catch_all=True,
        )
        return
    # * The demote gate must precede the decision write: record_mute queues a
    # * durable run, so a later "owner" verdict could not stop the worker.
    enforced_role = await demote_before_enforcement(
        bot,
        target_id,
        target_fname,
        trigger="mute",
        executor_id=admin_id,
        executor_fname=admin_fname,
    )
    if enforced_role == "owner":
        log.warning(
            "Mute refused: target=%d became Owner before the decision write", target_id
        )
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "identity.refuse.mute.owner",
                locale,
                line=Safe(user_ref(target_id, target_fname)),
            ),
            reply_markup=None,
            log_level="debug",
            log_label="Mute Owner protection",
            catch_all=True,
        )
        return

    # * The decision lands before the fan-out: no group is touched on a
    # * database failure. The decision and the live state are one record,
    # * so the mute and its history cannot disagree.
    record_r: BaseException | None = None
    run_id: int | None = None
    rule_ids, rule_note = rules_from_scope(meta, "mute")
    try:
        _, run_id = await db.mutes_db.record_mute(
            target_id,
            chat_id,
            reason_text,
            admin_id,
            until=until,
            requested_duration_seconds=(
                int(duration.total_seconds()) if duration is not None else None
            ),
            enforcement_chat_ids=[int(grp.get("chat_id", 0)) for grp in groups],
            proof_items=proof_upload.documents() if proof_upload else None,
            proof_expected_count=(
                proof_upload.expected_item_count if proof_upload else 0
            ),
            destination_chat_id=cfg.proofs[0],
            destination_thread_id=cfg.proofs[1],
            rule_item_ids=rule_ids,
            rule_selection_note=rule_note,
        )
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        record_r = exc
    if record_r is not None:
        log.error(
            "_execute_mute: mute DB write failed for target=%d (%s)",
            target_id,
            record_r,
        )
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "muting.note.db_fail",
                locale,
                user=Safe(user_ref(target_id, target_fname)),
            ),
            log_level="debug",
            log_label="_execute_mute DB-fail",
            catch_all=True,
        )
        return
    enforced_role = await demote_before_enforcement(
        bot,
        target_id,
        target_fname,
        trigger="mute",
        executor_id=admin_id,
        executor_fname=admin_fname,
    )
    if enforced_role == "owner":
        # * The target became Owner after the entry gates. The protected role
        # * cannot be demoted, and the helper returns it so the mute must stop
        # * before any group is restricted.
        log.warning(
            "Mute fan-out refused: target=%d became Owner before enforcement", target_id
        )
        await safe_edit_message(
            bot,
            prompt_chat,
            prompt_id,
            t(
                "identity.refuse.mute.owner",
                locale,
                line=Safe(user_ref(target_id, target_fname)),
            ),
            reply_markup=None,
            log_level="debug",
            log_label="Mute Owner protection",
            catch_all=True,
        )
        return
    applied = 0
    total = len(groups)
    failed = 0
    pending = 0
    failed_targets: list[dict[str, Any]] = []
    if run_id is not None:
        try:
            await enforcement_worker.deliver_queued_run(bot, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Mute delivery failed for run %s; it stays queued", run_id)
        try:
            report = await db.enforcement_db.run_report(run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Mute run report failed for run %s", run_id)
            report = None
        failed_targets = db.enforcement_db.failed_report_targets(report)
        delivery = db.enforcement_db.delivery_outcome(report, len(groups))
        total = delivery.total
        applied = delivery.applied
        failed = delivery.failed
        pending = delivery.pending
        for group in failed_targets:
            log.warning(
                "Mute enforcement left user=%d restricted nowhere in group=%s (%d)",
                target_id,
                group.get("title", ""),
                group.get("chat_id", 0),
            )
    else:
        restrict_coros = [
            bot.restrict_chat_member(
                grp.get("chat_id", 0),
                target_id,
                permissions=perms,
                until_date=until,
            )
            for grp in groups
        ]
        results = await fan_out(restrict_coros)
        outcome = summarize_fanout(groups, results, action="Mute", target_id=target_id)
        applied = outcome.applied
        total = outcome.total
        failed = outcome.failed
        failed_targets = [grp for grp, _exc in outcome.transient]
    proof_link: str | None = proof_upload.link if proof_upload else None
    proof_btn = buttons.action_proof_btn(target_id, proof_link, locale)
    notes: list[str] = []
    if failed:
        notes.append(
            t(
                "muting.summary.partial",
                locale,
                done=applied,
                total=total,
                failed=failed,
                sample=", ".join(
                    str(grp.get("title") or grp.get("chat_id", 0))
                    for grp in failed_targets[:5]
                ),
                more=" ..." if failed > 5 else "",
            )
        )
    if pending:
        notes.append(t("muting.summary.pending", locale, pending=pending))
    note = "".join(notes)
    summary = t(
        "muting.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        dur=Safe(bold(dur_str)),
        reason=reason_text,
        done=applied,
        total=total,
        note=Safe(note),
    )
    log_text = messages.mute_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason_text,
        dur_str,
    )
    log_send_r, edit_r = await asyncio.gather(
        send_log(
            bot,
            log_text,
            reply_markup=proof_btn,
        ),
        safe_edit_message(bot, prompt_chat, prompt_id, summary, reply_markup=proof_btn),
        return_exceptions=True,
    )
    throw_if_cancelled((log_send_r, edit_r))
    if isinstance(log_send_r, BaseException):
        log.error("Mute log send failed: %s", log_send_r)
    if isinstance(edit_r, BaseException):
        msg = update.effective_message
        if msg:
            await reply_rich(
                msg, summary, log_label="Mute summary fallback", reply_markup=proof_btn
            )


# ───────────────────────── Unmute executor ──────────────────────── #


async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Lift a federation mute through the durable enforcement ledger.

    The active mute is revoked and its restore run is queued in one
    transaction, so the groups that do not answer stay reachable for the
    worker even though the record is already revoked. A partial restore is
    reported with the failed group names and retried automatically.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    locale = await locale_for_update(update)
    try:
        active_mute = await db.mutes_db.get_active_mute(target_id)
    except Exception:
        log.exception("get_active_mute failed for target=%d", target_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute DB-fail",
            parse_mode=None,
        )
        return
    if active_mute is None:
        await reply_rich(
            msg,
            t(
                "muting.note.no_mute",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute no-mute",
        )
        return
    # * Fetch the group list before revoking: if it cannot be loaded we
    # * must abort with the mute record intact so a retry re-drives the
    # * full scope instead of losing the record to an empty target set.
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during unmute of %d", target_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute groups-fail",
            parse_mode=None,
        )
        return
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    chat_ids = [
        int(grp.get("chat_id", 0)) for grp in groups if int(grp.get("chat_id", 0) or 0)
    ]
    try:
        revoked, run_id = await db.mutes_db.revoke_mute_and_queue_unmute(
            target_id,
            admin.id,
            chat_ids,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "revoke_mute_and_queue_unmute failed for user=%d; aborting the "
            "unmute to avoid a record without its delivery run",
            target_id,
        )
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute DB-fail",
            parse_mode=None,
        )
        return
    if revoked == 0 or run_id is None:
        # * Another process revoked the mute between the read and the
        # * write. Reporting "no mute" is idempotent and claims no new
        # * change that this call did not make.
        await reply_rich(
            msg,
            t(
                "muting.note.no_mute",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute no-mute",
        )
        return
    # * The decision is committed; deliver now when this process can claim
    # * the run. A claim failure only means the scheduled worker owns it.
    try:
        await enforcement_worker.deliver_queued_run(ctx.bot, run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Unmute delivery failed for run %s; it stays queued", run_id)
    try:
        report = await db.enforcement_db.run_report(run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Unmute run report failed for run %s", run_id)
        report = None
    settled = db.enforcement_db.report_settled(report)
    failed_targets = db.enforcement_db.failed_report_targets(report)
    delivery = db.enforcement_db.delivery_outcome(report, len(groups))
    total = delivery.total
    failed = delivery.failed
    pending = delivery.pending
    transient = [(target, RuntimeError("delivery failed")) for target in failed_targets]
    applied_line = replies.applied_summary(
        locale,
        "muting.applied",
        total=total,
        failed=failed,
        pending=pending,
        transient=transient,
    )
    if report is None:
        # * The run exists and stays queued; only its report could not be
        # * read. Reporting a queued delivery is honest about that.
        note = t(
            "muting.note.unmute_queued",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            total=total,
        )
    elif total == 0:
        # * No group is connected any more, so there is nothing to
        # * restore and the run closed empty.
        note = t(
            "muting.unmute.body",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            applied=Safe(applied_line),
        )
    elif not settled:
        note = t(
            "muting.note.unmute_queued",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            total=total,
        )
    elif failed >= total:
        note = t(
            "muting.note.unmute_failed",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            applied=Safe(applied_line),
        )
    elif failed:
        note = t(
            "muting.note.unmute_partial",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            applied=Safe(applied_line),
        )
    else:
        note = t(
            "muting.unmute.body",
            locale,
            user=Safe(user_ref(target_id, target_name)),
            applied=Safe(applied_line),
        )
    log_text = messages.unmute_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
    )
    results = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        reply_rich(msg, note),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    if isinstance(results[0], BaseException):
        log.error("Unmute log send failed: %s", results[0])
    if isinstance(results[1], BaseException):
        log.debug("execute_unmute reply failed: %s", results[1])


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Copy mute data from the conversation scope, clean up, then call _execute_mute."""
    meta: dict[str, Any] = {}
    if ctx.user_data is not None:
        scope = flow_scope(ctx, update)
        meta = {k: v for k, v in scope.items() if k.startswith("mute_")}
        for k in list(meta):
            scope.pop(k, None)
    await _execute_mute(ctx.bot, update, meta)


# ─────────────────── ConversationHandler factory ────────────────── #


def mute_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the mute ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_mute,
        entry_filter,
        escape_filter=escape_filter,
        min_role="moderator",
        rules_enabled=True,
    )
