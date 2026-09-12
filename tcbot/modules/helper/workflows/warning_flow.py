# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warning executor + conversation factory."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.proof_flow import BuildProof, upload_proof
from tcbot.modules.helper.workflows.reason_flow import BuildReason, build_modaction_conv
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    is_benign_telegram_error,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

from telegram import Bot, InlineKeyboardMarkup, Message, Update

log = logging.getLogger(__name__)

# * Per-action BuildReason and BuildProof instances; imported by warnings.py
# * skip_allowed=False because warn requires a reason; Skip is not offered
reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")


# ──────────────────────────── Executors ─────────────────────────── #


async def execute_warn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_msgs: list[Message] | None = None,
) -> None:
    """Issue a warning and auto-ban the target if a warn threshold is reached.

    Two thresholds can trigger an automatic federation ban:

    1. **Per-group threshold** (``cfg.warn_limit``): fires when a user's warn count
       in the *current* group reaches or exceeds the configured limit. Uses
       ``>=`` so that a retry after a total enforcement failure still fires:
       warns are cleared only after successful enforcement, so a 0/N fan-out
       leaves the count at the limit and the next warn must re-drive the ban
       instead of wedging at limit+1. The ``already_banned`` guard in the
       auto-ban helper skips re-creation when the record already exists.

    2. **Federation-wide threshold** (``cfg.fed_warn_limit``, default 0 = off):
       fires when the user's total warns *across all groups* reach or exceed the
       configured value, even if no single group has hit its per-group limit.
       This closes the evasion path of spreading thin warns across many groups.

    In both cases a non-staff user is banned from all active federation
    groups. A target holding a federation role is demoted first and then
    exempted from the auto-ban (staff are never auto-banned via warnings);
    the warn itself is still recorded. When ``cfg.fed_warn_limit`` is 0
    only the per-group threshold applies (backward-compatible default).
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    admin = update.effective_user
    if admin is None:
        return
    admin_id = admin.id
    admin_fname = admin.first_name
    lc, lt = cfg.logs
    locale = await locale_for_update(update)

    # * Upload proof concurrently with the warn write: neither depends on the
    # * other, so awaiting them serially would add a full proof-channel round
    # * trip to every warn with evidence. On a warn-write failure the upload
    # * is cancelled so the failure reply stays immediate; an upload failure
    # * still degrades to no proof link, exactly as before.
    proof_task: asyncio.Task[int | None] | None = None
    pc, pt = cfg.proofs
    if proof_msgs:
        proof_caption = parse_logmsg.proof_caption_new(
            target_id, admin_id, admin_fname, utc_now()
        )
        proof_task = asyncio.create_task(
            upload_proof(ctx.bot, proof_msgs, proof_caption, pc, pt)
        )

    warn_limit = cfg.warn_limit
    # * Fail closed with a retry reply: without the stored warn the
    # * threshold check below is meaningless, and the conversation ends
    # * silently otherwise (the caller clears state and returns END).
    try:
        count = await db.warns_db.add_warn(target_id, reason_text, admin_id, chat_id)
    except Exception:
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        log.exception(
            "add_warn DB write failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warn DB-fail",
            parse_mode=None,
        )
        return

    proof_link: str | None = None
    if proof_task is not None:
        try:
            warn_proof_id = await proof_task
        except asyncio.CancelledError:
            proof_task.cancel()
            raise
        except Exception:
            log.warning("Warn proof upload skipped for target=%d", target_id)
            warn_proof_id = None
        if warn_proof_id:
            proof_link = message_link(pc, warn_proof_id, pt)

    proof_kb = keyboards.action_proof_kb(target_id, proof_link)
    log_text = parse_logmsg.warn_log(
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

    # ── Determine whether to auto-ban and record the trigger ────────
    # * "per_group": per-chat warn_limit reached for this group.
    # * "fed_global": federation-wide FED_WARN_LIMIT reached across all groups.
    # * None: below both thresholds; issue a plain warning only.
    #
    # * Per-group uses >= (not ==) so that a retry after a total enforcement
    # * failure still fires: warns are cleared only after successful
    # * enforcement, so a 0/N fan-out leaves the count at the limit and the
    # * next warn must re-drive the ban instead of wedging at limit+1 with
    # * no recovery path. A concurrent double-fire is safe: the auto-ban
    # * helper skips creation when an active ban already exists, and any
    # * duplicate active records are cleaned by deactivate_all_active_bans
    # * on unban.
    # * Federation-wide uses >= because the aggregation is a separate DB read
    # * and has no atomicity guarantee across chat boundaries; >= ensures no
    # * trigger is missed, and the already_banned guard below prevents double bans.
    auto_ban_trigger: str | None = None
    fed_count: int = 0

    if count >= warn_limit:
        auto_ban_trigger = "per_group"
    else:
        fed_limit = cfg.fed_warn_limit
        if fed_limit > 0:
            # * The warn above is already recorded; a failed aggregate read
            # * must not end the conversation silently. Report the recorded
            # * warn honestly and leave the federation-wide check to a retry.
            try:
                fed_count = await db.warns_db.federation_warn_count(target_id)
            except Exception:
                log.exception("federation_warn_count failed for target=%d", target_id)
                await safe_reply(
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
                    reply_markup=proof_kb,
                )
                return
            if fed_count >= fed_limit:
                auto_ban_trigger = "fed_global"

    if auto_ban_trigger is not None:
        await _execute_warn_auto_ban(
            ctx.bot,
            msg,
            target_id,
            target_name,
            admin_id,
            admin_fname,
            reason_text,
            count,
            warn_limit,
            fed_count,
            auto_ban_trigger,
            proof_kb,
            chat_id,
            lc,
            lt,
            log_text,
            locale,
        )
    else:
        # * federation log + reply in parallel
        results2 = await asyncio.gather(
            ctx.bot.send_message(
                lc,
                log_text,
                parse_mode="MarkdownV2",
                message_thread_id=lt,
                reply_markup=proof_kb,
            ),
            msg.reply_text(
                t(
                    "warnings.issued.body",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    count=count,
                    limit=warn_limit,
                    reason=reason_text,
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof_kb,
            ),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Warn log send failed: %s", results2[0])


async def execute_unwarn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Remove one warning from the target in the current group.

    Checks the current warn count; replies and returns early if the target has
    none. Otherwise decrements by one, logs the action, and sends the log and
    reply concurrently.
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)

    # * Fail closed with a retry reply instead of ending silently on outage.
    try:
        count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count read failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn DB-fail",
            parse_mode=None,
        )
        return
    if count == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn no-warns",
        )
        return

    new_count = max(count - 1, 0)
    chat_title = chat.title or str(chat_id)
    warn_limit = cfg.warn_limit
    admin = update.effective_user
    if admin is None:
        return
    lc, lt = cfg.logs
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    # * Remove first, then report what actually happened. Logging the
    # * computed new_count before the delete lands lies on concurrent
    # * unwarns: a second racing unwarn finds nothing to delete but the
    # * reply was already sent claiming success.
    try:
        removed = await db.warns_db.remove_last_warn(target_id, chat_id)
    except Exception:
        log.exception(
            "remove_last_warn DB write failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        removed = False
    if not removed:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn empty",
        )
        return
    # * Re-read the count after the delete so concurrent unwarns report
    # * the true remaining total instead of a stale computed value.
    try:
        new_count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count re-read failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        new_count = max(count - 1, 0)
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        ctx.bot.send_message(
            lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
        ),
        msg.reply_text(
            t(
                "warnings.removed.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                new=new_count,
                limit=warn_limit,
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error("Unwarn log send failed: %s", results[0])


async def execute_warnlist(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Reply with the numbered list of active warnings for the target in this group.

    Fetches all warnings from ``db.warns_db.get_warns`` and replies with a
    formatted list. Replies early if no warnings exist.
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)

    # * Fail closed with a retry reply instead of ending silently on outage.
    try:
        warns = await db.warns_db.get_warns(target_id, chat_id)
    except Exception:
        log.exception("get_warns read failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warnlist DB-fail",
            parse_mode=None,
        )
        return
    count = len(warns)

    if count == 0:
        await safe_reply(
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

    await safe_reply(msg, "\n".join(lines), log_label="execute_warnlist")


async def execute_resetwarns(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Clear all active warnings for the target in the current group.

    Calls ``db.warns_db.clear_warns`` and replies with the number of removed
    warnings. Replies early if the target has no warnings to clear.
    Logs the action to the mod log channel on success.
    """
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    lc, lt = cfg.logs
    locale = await locale_for_update(update)

    removed = 0
    try:
        removed = await db.warns_db.clear_warns(target_id, chat_id)
    except Exception:
        log.exception("clear_warns failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_resetwarns DB-fail",
            parse_mode=None,
        )
        return
    if removed == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none_clear.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_resetwarns no-warns",
        )
        return

    log_text = parse_logmsg.resetwarns_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        removed,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        ctx.bot.send_message(
            lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
        ),
        msg.reply_text(
            t(
                "warnings.cleared.body",
                locale,
                removed=removed,
                user=Safe(user_ref(target_id, target_name)),
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error(
            "Reset-warns log send failed for target=%d: %s", target_id, results[0]
        )


# ──────────────────────── Warn auto-ban helper ───────────────────── #
# * Extracted from execute_warn to keep the main flow under 200 lines.


async def _execute_warn_auto_ban(
    bot: Bot,
    msg: Message,
    target_id: int,
    target_name: str,
    admin_id: int,
    admin_fname: str,
    reason_text: str,
    count: int,
    warn_limit: int,
    fed_count: int,
    auto_ban_trigger: str,
    proof_kb: InlineKeyboardMarkup | None,
    chat_id: int,
    lc: int,
    lt: int | None,
    log_text: str,
    locale: str | None = None,
) -> None:
    """Handle warn-threshold auto-ban: staff demotion, DB record, fan-out, reply."""
    fed_warn_limit = cfg.fed_warn_limit
    # * The role lookup is guarded: the warn above is already recorded and the
    # * per-group trigger fires on exact equality, so letting a transient
    # * lookup failure propagate would both skip this threshold's auto-ban and
    # * wedge the retry (count is now limit+1, which never re-fires). Entry
    # * authorization already fail-closed; proceed as non-staff with a loud log.
    try:
        target_role = await db.users_roles.get_effective_role(target_id)
    except Exception:
        log.exception(
            "Warn auto-ban role lookup failed for target=%d; proceeding as non-staff",
            target_id,
        )
        target_role = None
    if target_role:
        demoted = True
        try:
            await Demote.execute(
                bot,
                target_id,
                target_name,
                target_role,
                admin_id,
                admin_fname,
                trigger="ban",
            )
        except Exception:
            demoted = False
            log.exception("Auto-demote on warn limit failed for role=%s", target_role)
        # * Only tell the admin the user was demoted when the demotion actually
        # * succeeded. If it failed (DB outage, race, etc.) the user still
        # * holds the role and the message must reflect that, otherwise the
        # * admin believes the role is gone and may forget to retry.
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
        await safe_reply(
            msg,
            exemption_text,
            log_label="Warn auto-ban staff exemption",
            reply_markup=proof_kb,
        )
        return

    groups_result, existing_ban, log_result = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.get_active_ban(target_id),
        bot.send_message(
            lc,
            log_text,
            parse_mode="MarkdownV2",
            message_thread_id=lt,
            reply_markup=proof_kb,
        ),
        return_exceptions=True,
    )
    if isinstance(log_result, BaseException):
        log.error("Warn-auto-ban log send failed: %s", log_result)
    log_msg_id: int = (
        log_result.message_id if not isinstance(log_result, BaseException) else 0
    )
    # * A groups-fetch failure must never silently shrink the enforcement
    # * scope: the reply below counts only fanned groups, so without this
    # * flag + suffix an outage would report full success while connected
    # * groups were skipped. The ban record exists, so /tcban stays a valid
    # * manual retry for anything missed.
    groups_fetch_failed = isinstance(groups_result, BaseException)
    if groups_fetch_failed:
        log.error(
            "Warn auto-ban groups fetch failed for target=%d; enforcing reduced scope",
            target_id,
        )
    groups: list = [] if groups_fetch_failed else groups_result
    already_banned = (
        not isinstance(existing_ban, BaseException) and existing_ban is not None
    )

    _all_group_ids: set[int] = {grp["chat_id"] for grp in groups}
    for _extra in [chat_id] + [cid for cid in (cfg.main_group, cfg.exec_group) if cid]:
        if _extra not in _all_group_ids:
            groups = [*groups, {"chat_id": _extra}]
            _all_group_ids.add(_extra)

    if not already_banned:
        try:
            await db.bans_db.create_ban(target_id, reason_text, admin_id, 0, log_msg_id)
        except Exception:
            # * Fail closed like execute_unban: enforcing chats without a DB
            # * record would leave an un-appealable, un-unbannable split
            # * brain (get_active_ban returns None and appeal submit
            # * revalidates the DB). No group is touched below, the
            # * threshold warn above stays recorded, and the admin retries
            # * via /tcban once the database recovers.
            log.exception(
                "Failed to create federation ban record on warn limit for user %d",
                target_id,
            )
            await safe_reply(
                msg,
                t(
                    "warnings.autoban.db_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                ),
                log_label="Warn auto-ban DB-fail",
                reply_markup=proof_kb,
            )
            return

    ban_results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )

    total_groups = len(groups)
    failed_groups = [
        (grp, r)
        for grp, r in zip(groups, ban_results, strict=False)
        if isinstance(r, BaseException)
    ]
    transient_groups = [
        (grp, r) for grp, r in failed_groups if not is_benign_telegram_error(r)
    ]
    failed = count_transient_errors(ban_results)
    applied = total_groups - failed
    any_ban_ok = applied > 0

    for grp, exc in failed_groups:
        log.warning(
            "Warn auto-ban enforcement failed for user=%d in group=%s (%d): %s",
            target_id,
            grp.get("title", ""),
            grp["chat_id"],
            exc,
        )
    log.info(
        "Warn auto-ban enforced (%s): target=%d applied=%d/%d",
        auto_ban_trigger,
        target_id,
        applied,
        total_groups,
    )

    if total_groups == 0:
        applied_line = t("warnings.autoban.empty", locale)
    elif failed == total_groups:
        sample = ", ".join(
            grp.get("title") or str(grp["chat_id"]) for grp, _ in transient_groups[:5]
        )
        applied_line = t(
            "warnings.autoban.none",
            locale,
            total=total_groups,
            sample=sample,
            more=" ..." if len(transient_groups) > 5 else "",
        )
    elif failed > 0:
        sample = ", ".join(
            grp.get("title") or str(grp["chat_id"]) for grp, _ in transient_groups[:3]
        )
        applied_line = t(
            "warnings.autoban.partial",
            locale,
            done=applied,
            total=total_groups,
            failed=failed,
            sample=sample,
            more=" ...)" if len(transient_groups) > 3 else ")",
        )
    else:
        applied_line = t("warnings.autoban.full", locale, total=total_groups)
    if groups_fetch_failed:
        applied_line += t("warnings.autoban.scope_warn", locale)

    if auto_ban_trigger == "per_group":
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
        clear_result, reply_result = await asyncio.gather(
            db.warns_db.clear_all_warns(target_id),
            msg.reply_text(
                f"{ban_notice}{applied_line}",
                parse_mode="MarkdownV2",
                reply_markup=proof_kb,
            ),
            return_exceptions=True,
        )
        if isinstance(clear_result, BaseException):
            log.error(
                "Warn clear after auto-ban failed for target=%d chat=%d: %s",
                target_id,
                chat_id,
                clear_result,
            )
        if isinstance(reply_result, BaseException):
            log.debug("Auto-ban notification reply failed: %s", reply_result)
    else:
        await safe_reply(
            msg,
            f"{ban_fail_notice}{applied_line}",
            log_label="Auto-ban failure notice",
            reply_markup=proof_kb,
        )


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop warn data from user_data and call execute_warn."""
    if ctx.user_data is None:
        log.warning("_exec_warn called without user_data")
        return
    target_id = ctx.user_data.pop("warn_target_id", 0)
    target_name = ctx.user_data.pop("warn_target_name", "")
    reason_text = ctx.user_data.pop("warn_reason", "")
    proof_msgs = ctx.user_data.pop("warn_proof_msgs", None)
    ctx.user_data.pop("warn_extra_info", None)
    await execute_warn(
        update,
        ctx,
        target_id,
        target_name,
        reason_text,
        proof_msgs=proof_msgs,
    )


# ─────────────────── ConversationHandler factory ────────────────── #


def warn_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the warn ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_warn,
        entry_filter,
        escape_filter=escape_filter,
    )
