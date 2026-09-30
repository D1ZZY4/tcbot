# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn-threshold auto-ban: staff demotion, record write, fan-out, reply."""

from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardMarkup, Message

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import replies
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    is_benign_telegram_error,
    throw_if_cancelled,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


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
    proof_msg_id: int | None = None,
) -> None:
    """Handle warn-threshold auto-ban: staff demotion, DB record, fan-out, reply."""
    fed_warn_limit = cfg.fed_warn_limit
    # * The role lookup fails closed: proceeding as non-staff on a transient
    # * failure could auto-ban an exempt staffer. Skipping is safe because the
    # * warn count persists and the >= trigger re-fires on the next warn.
    try:
        target_role = await db.users_roles.get_effective_role(target_id)
    except Exception:
        log.exception(
            "Warn auto-ban role lookup failed for target=%d; aborting auto-ban",
            target_id,
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="Warn auto-ban lookup-fail",
            parse_mode=None,
        )
        return
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
        # * Report demotion only when it succeeded; otherwise the admin would
        # * believe the role is gone and may forget to retry.
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

    groups_result, existing_ban = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.get_active_ban(target_id),
        return_exceptions=True,
    )
    # ! CRITICAL: cancelled reads must propagate before any enforcement
    # ! decision; coercing them shrinks the fan-out scope and may create
    # ! a ban record mid-shutdown.
    throw_if_cancelled((groups_result, existing_ban))
    # * A groups-fetch failure must never silently shrink the enforcement
    # * scope: the reply below counts only fanned groups, so without this
    # * flag + suffix an outage would report full success while connected
    # * groups were skipped. The ban record exists, so /tcban stays a valid
    # * manual retry for anything missed.
    groups_fetch_failed = isinstance(groups_result, BaseException)
    if groups_fetch_failed:
        log.exception(
            "Warn auto-ban groups fetch failed for target=%d; enforcing reduced scope",
            target_id,
        )
    groups: list = [] if groups_fetch_failed else groups_result
    already_banned = (
        not isinstance(existing_ban, BaseException) and existing_ban is not None
    )

    # * Connected groups plus the current chat plus primaries (single
    # * merge owner in groups_db).
    groups = db.groups_db.with_primary_groups(
        groups, (cfg.main_group, cfg.exec_group), chat_id
    )

    ban_id: str | None = None
    if not already_banned:
        try:
            # * Record first: sending the audit log before the record exists
            # * leaves a phantom card pointing at nothing when the write
            # * fails. The log message id is attached afterwards. The warn
            # * proof upload (when one was collected) becomes the ban proof
            # * so /check shows View Proof instead of an empty slot.
            ban_doc = await db.bans_db.create_ban(
                target_id, reason_text, admin_id, proof_msg_id or 0, 0
            )
            ban_id = ban_doc.get("ban_id", "")
        except Exception:
            # * Fail closed like execute_unban: enforcing chats without a DB
            # * record would leave an un-appealable, un-unbannable split
            # * brain. No group is touched below; the threshold warn stays
            # * recorded and the admin retries via /tcban once recovered.
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

    try:
        log_msg = await bot.send_message(
            lc,
            log_text,
            parse_mode="MarkdownV2",
            message_thread_id=lt,
            reply_markup=proof_kb,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Warn-auto-ban log send failed")
        log_msg = None
    if ban_id and log_msg is not None:
        try:
            await db.bans_db.set_log_message_id(ban_id, log_msg.message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Warn-auto-ban set_log_message_id failed")

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

    applied_line = replies.applied_summary(
        locale,
        "warnings.autoban",
        total=total_groups,
        failed=failed,
        transient=transient_groups,
    )
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
