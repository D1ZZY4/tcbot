# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warning actor, threshold ban, management, and conversation factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pyrogram.types import Message

from tcbot import cfg, enforcement_worker
from tcbot import database as db
from tcbot.modules.helper import buttons, guards, messages
from tcbot.modules.helper.context import Ctx, chat_id_of, display_name
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich, send_log
from tcbot.modules.helper.pipelines.demote_actions import (
    Demote,
    demote_before_enforcement,
)
from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    build_modaction_conv,
    rules_from_scope,
)
from tcbot.modules.helper.pipelines.proof_post import (
    ProofUpload,
    upload_proof_for_action,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import (
    fan_out,
    is_benign_telegram_error,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from pyrogram.filters import Filter as BaseFilter

log = get_logger(__name__)

reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")

# ────────────────────────── Warn executor ───────────────────────── #


async def execute_warn(
    ctx: Ctx,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_msgs: list[Message] | None = None,
) -> None:
    """Issue a warning and ban the target if a warn threshold is reached."""
    msg = ctx.effective_message
    if msg is None:
        return
    chat = ctx.effective_chat
    if chat is None:
        return
    chat_id = chat_id_of(chat)
    chat_title = chat.title or str(chat_id)
    admin = ctx.effective_user
    if admin is None:
        return
    admin_id = admin.id
    admin_fname = admin.first_name
    locale = await locale_for_update(ctx)
    warn_limit = cfg.warn_limit
    # * Re-check the executor against the target before anything is
    # * recorded or uploaded. The entry command compared the two roles,
    # * but the proof window can stay open for a minute, and a target
    # * promoted in that window must not be warned by a moderator who no
    # * longer outranks them. The check runs first so a refused warning
    # * leaves no record, no counter, no demotion, and no orphan proof.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="moderator",
        action="Warn",
        locale=locale,
    )
    if refusal is not None:
        await reply_rich(
            msg,
            refusal,
            log_label="execute_warn rank-refusal",
            parse_mode=None,
        )
        return
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
            log.warning("Warn proof upload skipped for target=%d", target_id)
    # * The proof upload can outlive a demotion or a target promotion.
    # * Repeat the fresh gate immediately before the warning is recorded.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="moderator",
        action="Warn",
        locale=locale,
    )
    if refusal is not None:
        await reply_rich(
            msg,
            refusal,
            log_label="execute_warn rank-refusal after proof",
            parse_mode=None,
        )
        return
    rule_ids, rule_note = rules_from_scope(flow_scope(ctx), "warn")
    try:
        count = await db.warns_db.add_warn(
            target_id,
            reason_text,
            admin_id,
            chat_id,
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
        log.exception(
            "add_warn DB write failed for target=%d chat=%d", target_id, chat_id
        )
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warn DB-fail",
            parse_mode=None,
        )
        return
    proof_link: str | None = proof_upload.link if proof_upload else None
    warn_proof_id: int | None = proof_upload.message_id if proof_upload else None
    proof_btn = buttons.action_proof_btn(target_id, proof_link, locale)
    log_text = messages.warn_log(
        target_id,
        target_name,
        admin_id,
        admin_fname,
        reason_text,
        count,
        warn_limit,
        chat_id,
        chat_title,
    )
    threshold_trigger: str | None = None
    fed_count: int = 0
    if count >= warn_limit:
        threshold_trigger = "per_group"
    else:
        fed_limit = cfg.fed_warn_limit
        if fed_limit > 0:
            try:
                fed_count = await db.warns_db.federation_warn_count(target_id)
            except Exception:
                log.exception("federation_warn_count failed for target=%d", target_id)
                await reply_rich(
                    msg,
                    t(
                        "warnings.fed_fail.body",
                        locale,
                        user=Safe(user_ref(target_id, target_name)),
                        count=count,
                        limit=warn_limit,
                        reason=reason_text,
                    ),
                    log_label="execute_warn fed-count-fail",
                    reply_markup=proof_btn,
                )
                return
            if fed_count >= fed_limit:
                threshold_trigger = "fed_global"
    if threshold_trigger is not None:
        fed_warn_limit = cfg.fed_warn_limit
        try:
            target_role = await db.users_roles.get_effective_role(target_id, fresh=True)
        except Exception:
            log.exception(
                "Warn threshold ban role lookup failed for target=%d; aborting threshold ban",
                target_id,
            )
            await reply_rich(
                msg,
                replies.err_db_retry(locale, plain=True),
                log_label="Warn threshold lookup-fail",
                parse_mode=None,
            )
            return
        # * Staff are exempt from warn threshold ban; demoted first so rank never survives.
        if target_role:
            demoted = False
            try:
                # * The return value is the source of truth: a role that was
                # * already gone is a no-op, and reporting it as a demotion
                # * would tell the moderator a rank was removed when it
                # * was not.
                demoted = await Demote.execute(
                    ctx.bot,
                    target_id,
                    target_name,
                    target_role,
                    admin_id,
                    admin_fname,
                    # * The staff exemption demotes instead of banning, so
                    # * the DM must not claim a federation ban.
                    trigger="warn",
                )
            except Exception:
                demoted = False
                log.exception("Demote on warn limit failed for role=%s", target_role)
            exemption_text = (
                t(
                    "warnings.exempt.demoted",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    role=target_role,
                )
                if demoted
                else t(
                    "warnings.exempt.failed",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    role=target_role,
                )
            )
            await reply_rich(
                msg,
                exemption_text,
                log_label="Warn threshold staff exemption",
                reply_markup=proof_btn,
            )
            return
        # * The exemption above read the role before the ban was recorded.
        # * A target promoted in that window would keep federation rank
        # * after the ban landed. Re-check and demote at enforcement time,
        # * exactly like the ban, kick, mute, and join paths, so a staff
        # * holder never keeps rank after the federation ban.
        enforced_role = await demote_before_enforcement(
            ctx.bot,
            target_id,
            target_name,
            # * This re-check precedes a real threshold ban, not the staff
            # * exemption above. Using the "warn" wording here would tell the
            # * target they were spared a ban while being banned moments later.
            trigger="ban",
            executor_id=admin_id,
            executor_fname=admin_fname,
        )
        if enforced_role == "owner":
            # * The target was promoted to Owner after the staff exemption
            # * read. The role is protected, so the automatic ban must not
            # * proceed.
            await reply_rich(
                msg,
                t(
                    "warnings.exempt.failed",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    role=db.users_roles.role_label("owner"),
                ),
                log_label="Warn threshold Owner protection",
                reply_markup=proof_btn,
            )
            return
        groups_result, existing_ban = await asyncio.gather(
            db.groups_db.active_groups(),
            db.bans_db.get_active_ban(target_id),
            return_exceptions=True,
        )
        throw_if_cancelled((groups_result, existing_ban))
        groups_fetch_failed = isinstance(groups_result, BaseException)
        if groups_fetch_failed:
            # * The failure came back as a gather value, not an active
            # * exception, so log the object itself instead of using
            # * log.exception, which would report "NoneType: None".
            log.error(
                "Warn threshold ban groups fetch failed for target=%d: %s; "
                "enforcing reduced scope",
                target_id,
                groups_result,
            )
        groups: list = [] if groups_fetch_failed else groups_result
        already_banned = (
            not isinstance(existing_ban, BaseException) and existing_ban is not None
        )
        groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,), chat_id)
        ban_id: str | None = None
        ban_run_id: int | None = None
        if not already_banned:
            try:
                # * The threshold ban is taken by the bot, not by a
                # * moderator, so it is an automated decision: the proof
                # * the moderator collected is optional here, and the
                # * decision stands on the warnings themselves.
                ban_doc = await db.bans_db.create_ban(
                    target_id,
                    reason_text,
                    admin_id,
                    warn_proof_id or 0,
                    0,
                    action_origin="automated",
                    origin_chat_id=chat_id,
                    proof_items=proof_upload.documents() if proof_upload else None,
                    proof_expected_count=(
                        proof_upload.expected_item_count if proof_upload else 0
                    ),
                    enforcement_chat_ids=[int(grp.get("chat_id", 0)) for grp in groups],
                    rule_item_ids=rule_ids,
                    rule_selection_note=rule_note,
                )
                ban_id = ban_doc.get("ban_id", "")
                ban_run_id = ban_doc.get("enforcement_run_id")
            except Exception:
                log.exception(
                    "Failed to create federation ban record on warn limit for user %d",
                    target_id,
                )
                await reply_rich(
                    msg,
                    t(
                        "warnings.autoban.db_fail",
                        locale,
                        user=Safe(user_ref(target_id, target_name)),
                    ),
                    log_label="Warn threshold DB-fail",
                    reply_markup=proof_btn,
                )
                return
        try:
            log_msg = await send_log(
                ctx.bot,
                log_text,
                reply_markup=proof_btn,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Warn threshold log send failed")
            log_msg = None
        if ban_id and log_msg is not None:
            try:
                await db.bans_db.set_log_message_id(ban_id, log_msg.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Warn threshold set_log_message_id failed")
        pending = 0
        if ban_run_id is not None:
            try:
                await enforcement_worker.deliver_queued_run(ctx.bot, ban_run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "Warn threshold ban delivery failed for run %s; it stays queued",
                    ban_run_id,
                )
            try:
                report = await db.enforcement_db.run_report(ban_run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Warn threshold run report failed for %s", ban_run_id)
                report = None
            failed_targets = db.enforcement_db.failed_report_targets(report)
            delivery = db.enforcement_db.delivery_outcome(report, len(groups))
            total_groups = delivery.total
            applied = delivery.applied
            failed_count = delivery.failed
            pending = delivery.pending
            landed_chat_ids = db.enforcement_db.landed_report_chat_ids(report)
            transient = [
                (
                    group,
                    RuntimeError("delivery failed"),
                )
                for group in failed_targets
            ]
        else:
            ban_results = await fan_out(
                [ctx.bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
            )
            outcome = summarize_fanout(
                groups, ban_results, action="Warn threshold ban", target_id=target_id
            )
            total_groups = outcome.total
            applied = outcome.applied
            failed_count = outcome.failed
            transient = list(outcome.transient)
            # * A benign refusal (bot removed, chat gone) means there is nobody
            # * to warn any more, so the group counts as landed here, matching
            # * summarize_fanout() and landed_report_chat_ids() on the queued
            # * path. Excluding it would leave an at-limit warning behind that
            # * re-fires a federation ban after the next unban.
            landed_chat_ids = [
                int(grp["chat_id"])
                for grp, result in zip(groups, ban_results, strict=True)
                if not isinstance(result, BaseException)
                or is_benign_telegram_error(result)
            ]
        # * ban_id only proves a decision row exists; it does not prove the
        # * ban landed anywhere. When every target fails permanently there is
        # * no enforcement even though the decision was recorded, so success
        # * must be derived from delivery state. A queued delivery still
        # * pending is not a failure, and an already-banned target needs no
        # * new delivery at all.
        any_ban_ok = already_banned or applied > 0 or pending > 0
        log.info(
            "Warn threshold ban enforced (%s): target=%d applied=%d/%d pending=%d",
            threshold_trigger,
            target_id,
            applied,
            total_groups,
            pending,
        )
        applied_line = replies.applied_summary(
            locale,
            "warnings.autoban",
            total=total_groups,
            failed=failed_count,
            pending=pending,
            transient=transient,
        )
        if groups_fetch_failed:
            applied_line += t("warnings.autoban.scope_warn", locale)
        if threshold_trigger == "per_group":
            ban_notice = t(
                "warnings.autoban.notice_per_group",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                limit=warn_limit,
            )
            ban_fail_notice = t(
                "warnings.autoban.fail_per_group",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                limit=warn_limit,
            )
        else:
            ban_notice = t(
                "warnings.autoban.notice_fed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                fed=fed_count,
                fedlimit=fed_warn_limit,
            )
            ban_fail_notice = t(
                "warnings.autoban.fail_fed",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                fed=fed_count,
                fedlimit=fed_warn_limit,
            )
        if any_ban_ok:
            # * The reply is best-effort: a failed notification must not
            # * skip the warn cleanup below.
            try:
                await reply_rich(
                    msg,
                    f"{ban_notice}{applied_line}",
                    reply_markup=proof_btn,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("Threshold ban notification reply failed: %s", exc)
            # * The warn slate is cleared only where the ban actually landed.
            # * Clearing everything after a partial enforcement left the
            # * failed groups with no warning and no ban, so their threshold
            # * could never fire again. A complete enforcement clears the
            # * whole slate so a later unban does not re-ban on stale counts.
            try:
                await _clear_warns_after_threshold_ban(
                    target_id,
                    groups,
                    landed_chat_ids,
                    scope_complete=not groups_fetch_failed,
                )
            except Exception:
                # * The clear helper re-raises on failure. Cancellation is a
                # * BaseException and still propagates to the caller.
                log.exception(
                    "Warn clear after threshold ban failed for target=%d chat=%d",
                    target_id,
                    chat_id,
                )
        else:
            await reply_rich(
                msg,
                f"{ban_fail_notice}{applied_line}",
                log_label="Threshold ban failure notice",
                reply_markup=proof_btn,
            )
        return
    results2 = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
            reply_markup=proof_btn,
        ),
        reply_rich(
            msg,
            t(
                "warnings.issued.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                count=count,
                limit=warn_limit,
                reason=reason_text,
            ),
            reply_markup=proof_btn,
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results2)
    if isinstance(results2[0], BaseException):
        log.error("Warn log send failed: %s", results2[0])


# ───────────────────────── Warn management ──────────────────────── #


async def _clear_warns_after_threshold_ban(
    target_id: int,
    groups: list[dict[str, Any]],
    landed_chat_ids: list[int],
    *,
    scope_complete: bool = True,
) -> Any:
    """Clear the warn slate of the groups the threshold ban reached.

    A complete enforcement clears every group so a later unban does not
    re-ban on stale counts. A partial enforcement clears only the groups
    where the ban landed: the failed groups keep their warnings so their
    threshold can fire again once the enforcement succeeds. A reduced
    scope is never complete even when every group in it accepted the ban,
    because the groups that could not be loaded were never attempted.
    """
    if scope_complete and len(landed_chat_ids) >= len(groups):
        return await db.warns_db.clear_all_warns(target_id)
    log.warning(
        "Warn threshold ban applied to %d/%d known groups for target=%d "
        "(complete scope=%s); warnings kept outside the reached groups.",
        len(landed_chat_ids),
        len(groups),
        target_id,
        scope_complete,
    )
    return await db.warns_db.clear_warns_for_chats(target_id, landed_chat_ids)


async def execute_unwarn(
    ctx: Ctx,
    target_id: int,
    target_name: str,
) -> None:
    """Remove one warning from the target in the current group."""
    msg = ctx.effective_message
    if msg is None:
        return
    chat = ctx.effective_chat
    if chat is None:
        return
    chat_id = chat_id_of(chat)
    locale = await locale_for_update(ctx)
    try:
        count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count read failed for target=%d chat=%d", target_id, chat_id
        )
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn DB-fail",
            parse_mode=None,
        )
        return
    if count == 0:
        await reply_rich(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn no-warns",
        )
        return
    chat_title = chat.title or str(chat_id)
    warn_limit = cfg.warn_limit
    admin = ctx.effective_user
    if admin is None:
        return
    try:
        removed = await db.warns_db.remove_last_warn(target_id, chat_id)
    except Exception:
        log.exception(
            "remove_last_warn DB write failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn db_retry",
            parse_mode=None,
        )
        return
    if not removed:
        await reply_rich(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn empty",
        )
        return
    try:
        new_count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count re-read failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        new_count = max(count - 1, 0)
    log_text = messages.unwarn_log(
        target_id,
        target_name,
        admin.id,
        display_name(admin),
        new_count,
        warn_limit,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        reply_rich(
            msg,
            t(
                "warnings.removed.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                new=new_count,
                limit=warn_limit,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    if isinstance(results[0], BaseException):
        log.error("Unwarn log send failed: %s", results[0])


async def execute_warnlist(
    ctx: Ctx,
    target_id: int,
    target_name: str,
) -> None:
    """Reply with the numbered list of active warnings for the target."""
    msg = ctx.effective_message
    if msg is None:
        return
    chat = ctx.effective_chat
    if chat is None:
        return
    chat_id = chat_id_of(chat)
    locale = await locale_for_update(ctx)
    try:
        # * Cap the numbered render: a pathological history must not
        # * become an unbounded message. Total count stays honest via
        # * the header; the list shows the 50 most recent.
        warns = await db.warns_db.get_warns(
            target_id, chat_id, newest_first=True, limit=50
        )
    except Exception:
        log.exception("get_warns read failed for target=%d chat=%d", target_id, chat_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warnlist DB-fail",
            parse_mode=None,
        )
        return
    try:
        total = await db.warns_db.warn_count(target_id, chat_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        total = len(warns)
    count = max(total, len(warns))
    if count == 0:
        await reply_rich(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_warnlist no-warns",
        )
        return
    header = t(
        "warnings.list.header",
        locale,
        user=Safe(user_ref(target_id, target_name)),
        count=count,
        limit=cfg.warn_limit,
    )
    lines = [header]
    for i, w in enumerate(warns, 1):
        lines.append(
            t(
                "warnings.list.item",
                locale,
                i=i,
                reason=w.get("reason", "")
                or t("warnings.list.no_reason", locale, plain=True),
            )
        )
    await reply_rich(msg, "\n".join(lines), log_label="execute_warnlist")


async def execute_resetwarns(
    ctx: Ctx,
    target_id: int,
    target_name: str,
) -> None:
    """Clear all active warnings for the target in the current group."""
    msg = ctx.effective_message
    if msg is None:
        return
    admin = ctx.effective_user
    if admin is None:
        return
    chat = ctx.effective_chat
    if chat is None:
        return
    chat_id = chat_id_of(chat)
    chat_title = chat.title or str(chat_id)
    locale = await locale_for_update(ctx)
    removed = 0
    try:
        removed = await db.warns_db.clear_warns(target_id, chat_id)
    except Exception:
        log.exception("clear_warns failed for target=%d chat=%d", target_id, chat_id)
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_resetwarns DB-fail",
            parse_mode=None,
        )
        return
    if removed == 0:
        await reply_rich(
            msg,
            t(
                "warnings.none_clear.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_resetwarns no-warns",
        )
        return
    log_text = messages.resetwarns_log(
        target_id,
        target_name,
        admin.id,
        display_name(admin),
        removed,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        reply_rich(
            msg,
            t(
                "warnings.cleared.body",
                locale,
                removed=removed,
                user=Safe(user_ref(target_id, target_name)),
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    if isinstance(results[0], BaseException):
        # * This is a captured gather value, not an active exception; using
        # * log.exception here would attach a spurious "NoneType: None".
        log.error(
            "Reset-warns log send failed for target=%d: %s", target_id, results[0]
        )


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_warn(ctx: Ctx) -> None:
    """Pop warn data from the conversation scope and call execute_warn."""
    if ctx.user_data is None:
        log.warning("_exec_warn called without user_data")
        return
    scope = flow_scope(ctx)
    target_id = scope.pop("warn_target_id", 0)
    target_name = scope.pop("warn_target_name", "")
    reason_text = scope.pop("warn_reason", "")
    proof_msgs = scope.pop("warn_proof_msgs", None)
    scope.pop("warn_extra_info", None)
    await execute_warn(ctx, target_id, target_name, reason_text, proof_msgs=proof_msgs)


# ─────────────────── ConversationHandler factory ────────────────── #


def warn_conversation(
    entry_fn: Callable[..., object],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the warn ConversationHandler via the central mod_action_steps factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_warn,
        entry_filter,
        escape_filter=escape_filter,
        min_role="moderator",
        rules_enabled=True,
    )
