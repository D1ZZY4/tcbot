# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Warning executor + conversation factory."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import esc, user_ref
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.proof_flow import BuildProof, upload_proof
from tcbot.modules.helper.workflows.reason_flow import BuildReason, build_modaction_conv
from tcbot.utils.dispatch import fan_out
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

WARN_LIMIT = 3

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
    proof_desc: str | None = None,
    proof_msgs: list | None = None,
) -> None:
    """Issue a warning and auto-ban the target if a warn threshold is reached.

    Two thresholds can trigger an automatic federation ban:

    1. **Per-group threshold** (``WARN_LIMIT``): fires when a user's warn count
       in the *current* group reaches exactly ``WARN_LIMIT``.  Uses ``==`` so
       that concurrent warns at limit+1 don't double-fire.

    2. **Federation-wide threshold** (``cfg.fed_warn_limit``, default 0 = off):
       fires when the user's total warns *across all groups* reach or exceed the
       configured value, even if no single group has hit its per-group limit.
       This closes the evasion path of spreading thin warns across many groups.

    In both cases any held federation role is demoted first, then the user is
    banned from all active federation groups.  When ``cfg.fed_warn_limit`` is 0
    only the per-group threshold applies (backward-compatible default).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    admin_fname = update.effective_user.first_name
    chat_title = update.effective_chat.title or str(chat_id)
    lc, lt = cfg.logs

    proof_link: str | None = None
    if proof_msgs:
        try:
            pc, pt = cfg.proofs
            caption = parse_logmsg.proof_caption_new(
                target_id, admin_id, admin_fname, utc_now()
            )
            warn_proof_id = await upload_proof(ctx.bot, proof_msgs, caption, pc, pt)
            if warn_proof_id:
                proof_link = message_link(pc, warn_proof_id, pt)
        except Exception:
            log.warning("Warn proof upload skipped for target=%d", target_id)

    proof_kb = keyboards.action_proof_kb(target_id, proof_link)

    count = await db.warns_db.add_warn(target_id, reason_text, admin_id, chat_id)
    log_text = parse_logmsg.warn_log(
        target_id,
        target_name,
        admin_id,
        admin_fname,
        reason_text,
        count,
        WARN_LIMIT,
        chat_id,
        chat_title,
    )

    # ── Determine whether to auto-ban and record the trigger ────────
    # * "per_group": per-chat WARN_LIMIT reached for this group.
    # * "fed_global": federation-wide FED_WARN_LIMIT reached across all groups.
    # * None: below both thresholds; issue a plain warning only.
    #
    # * Per-group uses == (not >=) so that only the exact hit triggers the ban;
    # * a concurrent second warn returns WARN_LIMIT+1 and is silently skipped,
    # * preventing a double-ban race condition.
    # * Federation-wide uses >= because the aggregation is a separate DB read
    # * and has no atomicity guarantee across chat boundaries; >= ensures no
    # * trigger is missed, and the already_banned guard below prevents double bans.
    auto_ban_trigger: str | None = None
    fed_count: int = 0

    if count == WARN_LIMIT:
        auto_ban_trigger = "per_group"
    else:
        fed_limit = cfg.fed_warn_limit
        if fed_limit > 0:
            fed_count = await db.warns_db.federation_warn_count(target_id)
            if fed_count >= fed_limit:
                auto_ban_trigger = "fed_global"

    if auto_ban_trigger is not None:
        # * If the target somehow holds a federation role (e.g. promoted mid-warn-cycle),
        # * remove the role before the auto-ban so they don't keep staff perms after exile.
        target_role = await db.users_roles.get_effective_role(target_id)
        if target_role:
            try:
                await Demote.execute(
                    ctx.bot,
                    target_id,
                    target_name,
                    target_role,
                    admin_id,
                    admin_fname,
                    trigger="ban",
                )
            except Exception:
                log.exception("Auto-demote on warn limit failed")

        # * Federation ban: fetch active groups + check existing ban + send log in parallel.
        # * Overlapping the DB reads with the log send keeps total latency low.
        groups_result, existing_ban, log_result = await asyncio.gather(
            db.groups_db.active_groups(),
            db.bans_db.get_active_ban(target_id),
            ctx.bot.send_message(
                lc, log_text, parse_mode="HTML", message_thread_id=lt, reply_markup=proof_kb
            ),
            return_exceptions=True,
        )
        if isinstance(log_result, BaseException):
            log.error("Warn-auto-ban log send failed: %s", log_result)
        log_msg_id: int = (
            log_result.message_id if not isinstance(log_result, BaseException) else 0
        )
        groups: list = (
            groups_result if not isinstance(groups_result, BaseException) else []
        )
        already_banned = (
            not isinstance(existing_ban, BaseException) and existing_ban is not None
        )

        # * Ensure the originating chat and primary groups are included even if they
        # * are not in federated_groups (primary groups are env-var-configured only).
        _all_group_ids: set[int] = {grp["chat_id"] for grp in groups}
        for _extra in [chat_id] + [
            cid for cid in (cfg.main_group, cfg.exec_group) if cid
        ]:
            if _extra not in _all_group_ids:
                groups = [*groups, {"chat_id": _extra}]
                _all_group_ids.add(_extra)

        # * Create DB ban record only when the user is not already federation-banned.
        # * proof_msg_id=0 because warn auto-bans have no uploaded proof media.
        if not already_banned:
            try:
                await db.bans_db.create_ban(
                    target_id, reason_text, admin_id, 0, log_msg_id
                )
            except Exception:
                log.exception(
                    "Failed to create federation ban record on warn limit for user %d",
                    target_id,
                )

        # * Fan-out ban to all federation groups concurrently (rate-limited by fan_out).
        ban_results = await fan_out(
            [ctx.bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
        )

        total_groups = len(groups)
        failed_groups = [
            (grp, r)
            for grp, r in zip(groups, ban_results, strict=False)
            if isinstance(r, BaseException)
        ]
        failed = len(failed_groups)
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

        # * Build the applied-to summary line (mirrors ban_flow.py style).
        if total_groups == 0:
            applied_line = " No connected groups configured."
        elif failed == total_groups:
            sample = ", ".join(
                grp.get("title") or str(grp["chat_id"]) for grp, _ in failed_groups[:5]
            )
            applied_line = (
                f" WARNING: ban not enforced in any group ({total_groups}/{total_groups} failed)."
                f" Check bot admin rights in: {esc(sample)}"
                + (" ..." if len(failed_groups) > 5 else "")
            )
        elif failed > 0:
            sample = ", ".join(
                grp.get("title") or str(grp["chat_id"]) for grp, _ in failed_groups[:3]
            )
            applied_line = (
                f" Applied to {applied}/{total_groups} groups"
                f" ({failed} failed: {esc(sample)}"
                + (" ..." if len(failed_groups) > 3 else ")")
            )
        else:
            applied_line = f" Applied to {total_groups}/{total_groups} groups."

        # * Build reply text based on which threshold fired.
        if auto_ban_trigger == "per_group":
            ban_notice = (
                f"{user_ref(target_id, target_name)} "
                f"hit {WARN_LIMIT} warnings "
                f"and has been federation-banned."
            )
            ban_fail_notice = (
                f"{user_ref(target_id, target_name)} "
                f"hit {WARN_LIMIT} warnings "
                f"but federation-ban failed - please ban them manually."
            )
        else:
            ban_notice = (
                f"{user_ref(target_id, target_name)} "
                f"hit {fed_count}/{cfg.fed_warn_limit} warnings across the federation "
                f"and has been federation-banned."
            )
            ban_fail_notice = (
                f"{user_ref(target_id, target_name)} "
                f"hit {fed_count}/{cfg.fed_warn_limit} federation-wide warnings "
                f"but federation-ban failed - please ban them manually."
            )

        if any_ban_ok:
            # * Clear warns in the originating chat and reply with federation-ban notice.
            clear_result, reply_result = await asyncio.gather(
                db.warns_db.clear_warns(target_id, chat_id),
                msg.reply_text(
                    f"{ban_notice}{applied_line}",
                    parse_mode="HTML",
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
            try:
                await msg.reply_text(
                    f"{ban_fail_notice}{applied_line}",
                    parse_mode="HTML",
                    reply_markup=proof_kb,
                )
            except Exception as exc:
                log.debug("Auto-ban failure notice reply failed: %s", exc)
    else:
        # * federation log + reply in parallel
        results2 = await asyncio.gather(
            ctx.bot.send_message(
                lc, log_text, parse_mode="HTML", message_thread_id=lt, reply_markup=proof_kb
            ),
            msg.reply_text(
                f"{user_ref(target_id, target_name)} has been warned "
                f"({count}/{WARN_LIMIT}) - {esc(reason_text)}",
                parse_mode="HTML",
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
    chat_id = update.effective_chat.id

    count = await db.warns_db.warn_count(target_id, chat_id)
    if count == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings in this group.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_unwarn no-warns reply failed: %s", exc)
        return

    new_count = max(count - 1, 0)
    chat_title = update.effective_chat.title or str(chat_id)
    admin = update.effective_user
    lc, lt = cfg.logs
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        WARN_LIMIT,
        chat_id,
        chat_title,
    )
    # * remove warn + send log + reply in parallel
    results = await asyncio.gather(
        db.warns_db.remove_last_warn(target_id, chat_id),
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"One warning removed from {user_ref(target_id, target_name)}. "
            f"They're now at {new_count}/{WARN_LIMIT}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error(
            "remove_last_warn DB write failed for target=%d chat=%d: %s",
            target_id,
            chat_id,
            results[0],
        )
    if isinstance(results[1], BaseException):
        log.error("Unwarn log send failed: %s", results[1])


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
    chat_id = update.effective_chat.id

    warns = await db.warns_db.get_warns(target_id, chat_id)
    count = len(warns)

    if count == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings in this group.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_warnlist no-warns reply failed: %s", exc)
        return

    lines = [f"{user_ref(target_id, target_name)} has {count}/{WARN_LIMIT} warnings:\n"]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {esc(w.get('reason', 'No reason'))}")

    try:
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as exc:
        log.debug("execute_warnlist reply failed: %s", exc)


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
    admin = update.effective_user
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or str(chat_id)
    lc, lt = cfg.logs

    removed = await db.warns_db.clear_warns(target_id, chat_id)
    if removed == 0:
        try:
            await msg.reply_text(
                f"{user_ref(target_id, target_name)} has no warnings to clear.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("execute_resetwarns no-warns reply failed: %s", exc)
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
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"All {removed} warning(s) cleared for {user_ref(target_id, target_name)}. Clean slate.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error(
            "Reset-warns log send failed for target=%d: %s", target_id, results[0]
        )


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop warn data from user_data and call execute_warn."""
    target_id = ctx.user_data.pop("warn_target_id", 0)
    target_name = ctx.user_data.pop("warn_target_name", "")
    reason_text = ctx.user_data.pop("warn_reason", "")
    proof_desc = ctx.user_data.pop("warn_proof_desc", None)
    proof_msgs = ctx.user_data.pop("warn_proof_msgs", None)
    ctx.user_data.pop("warn_extra_info", None)
    await execute_warn(
        update, ctx, target_id, target_name, reason_text,
        proof_desc=proof_desc, proof_msgs=proof_msgs,
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
