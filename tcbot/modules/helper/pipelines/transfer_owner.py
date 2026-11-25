# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation ownership transfer executor."""

from __future__ import annotations

import asyncio

from tcbot import database as db
from tcbot.modules.helper import identity
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.extraction import extract_target
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    ownership_transferred,
    replies,
    reply_rich,
    send_log,
)
from tcbot.modules.helper.pipelines.errors import report as error_reporter
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

log = get_logger(__name__)


async def execute_transfer(ctx: Ctx) -> None:
    """Transfer federation ownership to another user.

    Resolves the new owner target and runs the identity checks, then swaps
    the owner and grants the previous Owner the Admin role in one
    transaction. A failed transaction leaves both roles untouched instead of
    leaving the federation ownerless or the former Owner without a role.
    Logs and the confirmation reply run in parallel afterward.
    """
    locale = await locale_for_update(ctx)
    current_owner = ctx.effective_user
    msg = ctx.effective_message
    if current_owner is None or msg is None:
        return

    args = parse_cmd_args(msg.text)
    try:
        target_id, target_fname = await extract_target(ctx, args, ctx.bot)
    except Exception:
        log.exception("extract_target failed during transfer")
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer extract-failed",
            parse_mode=None,
        )
        return
    if not target_id:
        await reply_rich(
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
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer classify-failed",
            parse_mode=None,
        )
        return
    refusal = identity.refuse_message("transfer", ident, locale)
    if refusal is not None:
        await reply_rich(msg, refusal, log_label="cmd_transfer refusal")
        return

    # * A bot owner would brick federation leadership, so transfer fails
    # * closed on an indeterminate check: only a verified human proceeds.
    # * Promotion keeps the best-effort gate where unknown stays allowed.
    verified_human = await identity.verify_not_bot(ctx, target_id, ctx.bot)
    if verified_human is False:
        await reply_rich(
            msg,
            t("admins.error.bot_target", locale, plain=True),
            log_label="cmd_transfer bot-target",
            parse_mode=None,
        )
        return
    if verified_human is None:
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer unverified-target",
            parse_mode=None,
        )
        return

    # * Banned users must not gain owner powers: fail closed on active
    # * ban (and on the lookup itself) so appeal/unban comes first.
    try:
        target_ban = await db.bans_db.get_active_ban(target_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("cmd_transfer ban lookup failed for %d", target_id)
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer ban-lookup-failed",
            parse_mode=None,
        )
        return
    if target_ban is not None:
        await reply_rich(
            msg,
            t("admins.error.banned_target", locale, plain=True),
            log_label="cmd_transfer banned-target",
            parse_mode=None,
        )
        return

    target_uname = ident.username

    # * Ownership may have moved while the target was classified and
    # * verified. Re-read it at the mutation point, so a second in-flight
    # * transfer cannot overwrite a newer owner and a demoted owner
    # * cannot hand the federation over. A failed lookup refuses.
    try:
        still_owner = await db.users_roles.is_owner(current_owner.id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("cmd_transfer owner re-check failed")
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_transfer owner-check-failed",
            parse_mode=None,
        )
        return
    if not still_owner:
        await reply_rich(
            msg,
            replies.err_perm_expired(locale, plain=True),
            log_label="cmd_transfer owner-changed",
            parse_mode=None,
        )
        return

    # * The target's existing role is cleared inside transfer_ownership.
    # * Revoking it here would be a second, non-atomic side effect: a failed
    # * transfer would leave the target stripped of a role it still held.
    # * The transaction swaps the owner, grants the previous Owner Admin,
    # * and revokes every active assignment of the new owner together.

    # * The swap and the previous Owner's Admin grant are one transaction,
    # * so a failure cannot leave the federation ownerless or leave the
    # * former Owner with no role.
    try:
        await db.users_roles.transfer_ownership(current_owner.id, target_id)
    except Exception:
        log.exception("cmd_transfer failed for target %d", target_id)
        await reply_rich(
            msg,
            t("admins.transfer.set_owner_fail", locale, plain=True),
            log_label="cmd_transfer transfer-failed",
            parse_mode=None,
        )
        return
    # * Point infra error DMs at the new owner from here on.
    error_reporter.set_owner(target_id)
    # * A promotion request filed before the transfer would now target the
    # * Owner. It is cancelled so the card cannot be approved later; a
    # * failure is non-fatal because the approval path refuses the Owner
    # * role on its own.
    try:
        cancelled = await db.queues_db.cancel_pending_for_user(
            target_id, current_owner.id
        )
    except Exception:
        log.exception("cmd_transfer cancel pending request failed for %d", target_id)
    else:
        if cancelled:
            log.info(
                "cmd_transfer cancelled %d pending promotion request(s) for new owner %d",
                cancelled,
                target_id,
            )
    # * The atomic transfer already granted the previous Owner the Admin
    # * role, so the reply no longer has a partial-success warning.
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
    transfer_log_r, transfer_reply_r = await asyncio.gather(
        send_log(
            ctx.bot,
            log_text,
        ),
        reply_rich(msg, transfer_note),
        return_exceptions=True,
    )
    throw_if_cancelled((transfer_log_r, transfer_reply_r))
    if isinstance(transfer_log_r, BaseException):
        log.error("Ownership transfer log send failed: %s", transfer_log_r)
    if isinstance(transfer_reply_r, BaseException):
        log.debug("Ownership transfer reply failed: %s", transfer_reply_r)
