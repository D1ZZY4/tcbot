# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation ownership transfer command."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.admins.shared import _RL_BULK_LIMIT, _RL_PERIOD_BULK_S
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_logmsg import ownership_transferred
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils import error_reporter
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Transfer federation ownership to another user.

    Resolves the new owner target, runs identity checks, then replaces the
    owner record via ``set_owner`` first and keeps the previous Founder as
    Admin via ``add_admin`` second. ``set_owner`` first keeps the federation
    from ever going ownerless on a mid-flight failure; a failed ``add_admin``
    stays visible as a WARNING line in the reply. Logs and confirmation
    reply run in parallel afterward.
    """
    locale = await locale_for_update(update)
    current_owner = update.effective_user
    msg = update.effective_message
    if current_owner is None or msg is None:
        return

    args = parse_cmd_args(msg.text)
    try:
        target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    except Exception:
        log.exception("extract_target failed during transfer")
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer extract-failed",
            parse_mode=None,
        )
        return
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_transfer no-target",
            parse_mode=None,
        )
        return

    try:
        ident = await identity.classify(
            ctx.bot, current_owner.id, target_id, target_fname
        )
    except Exception:
        log.exception("identity.classify failed during transfer")
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer classify-failed",
            parse_mode=None,
        )
        return
    refusal = identity.refuse_message("transfer", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_transfer refusal")
        return

    # * A bot owner would brick federation leadership, so the same
    # * verified-only check as promotion applies; unknown stays allowed.
    if await identity.is_proven_bot(update, target_id, ctx.bot):
        await safe_reply(
            msg,
            t("admins.error.bot_target", locale, plain=True),
            log_label="cmd_transfer bot-target",
            parse_mode=None,
        )
        return

    target_uname = ident.username

    # * Rank-check the target so the new owner keeps no residual
    # * Developer/Tester role beside the Founder record. Clear via
    # * Demote.remove_role (not the bare helper) so an Admin target leaves
    # * tc_admins rather than a stale row the next demote would resurrect.
    role_check = await resolve_and_check(
        msg, current_owner.id, target_id, min_role="developer"
    )
    if role_check == (None, None):
        return
    _executor_role, target_role = role_check
    if target_role and target_role != "founder":
        try:
            await Demote.remove_role(target_id, target_role)
            log.info(
                "cmd_transfer cleared pre-existing role %s from new owner %d",
                target_role,
                target_id,
            )
        except Exception as exc:
            log.warning(
                "cmd_transfer remove_role failed for new owner %d: %s",
                target_id,
                exc,
            )

    # * set_owner first in one upsert write (a crash there cannot leave zero
    # * owners). add_admin runs second and is non-fatal so a transient
    # * failure there never leaves the federation ownerless.
    try:
        await db.users_roles.set_owner(target_id)
    except Exception:
        log.exception("cmd_transfer set_owner failed for target %d", target_id)
        await safe_reply(
            msg,
            t("admins.transfer.set_owner_fail", locale, plain=True),
            log_label="cmd_transfer set-owner-failed",
            parse_mode=None,
        )
        return
    # * Point infra error DMs at the new owner from here on.
    error_reporter.set_owner(target_id)
    # * Non-fatal but never silent: set_owner already committed, so flag a
    # * failed add_admin in the reply instead of claiming full success.
    prev_owner_admin_ok = True
    try:
        await db.users_roles.add_admin(current_owner.id, current_owner.id)
    except Exception:
        prev_owner_admin_ok = False
        log.exception("cmd_transfer add_admin failed after set_owner")
    lc, lt = cfg.logs
    log_text = ownership_transferred(
        target_id,
        target_fname or str(target_id),
        current_owner.id,
        current_owner.first_name or "unknown",
    )
    transfer_note = t(
        "admins.transfer.done",
        locale,
        user=Safe(user_ref(target_id, target_fname or str(target_id), target_uname)),
    )
    if not prev_owner_admin_ok:
        transfer_note += t(
            "admins.transfer.admin_warn",
            locale,
            user=Safe(
                user_ref(current_owner.id, current_owner.first_name or "unknown")
            ),
        )
    transfer_log_r, transfer_reply_r = await asyncio.gather(
        ctx.bot.send_message(
            lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
        ),
        msg.reply_text(
            transfer_note,
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    if isinstance(transfer_log_r, BaseException):
        log.error("Ownership transfer log send failed: %s", transfer_log_r)
    if isinstance(transfer_reply_r, BaseException):
        log.debug("Ownership transfer reply failed: %s", transfer_reply_r)
