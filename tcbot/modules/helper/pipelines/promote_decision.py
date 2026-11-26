# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Approve / reject decisions on promotion request cards."""

from __future__ import annotations

import asyncio

from pyrogram.types import CallbackQuery

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.context import Ctx, display_name
from tcbot.modules.helper.guards import banned_target_refusal
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import (
    answer_ack,
    answer_alert,
    cb_error_edit,
    promote_approved_log,
    promote_rejected_log,
    promote_request_log,
    replies,
    safe_edit_cb,
    send_log,
    send_text,
)
from tcbot.modules.helper.rich.edit_msg import callback_text_of
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


async def _still_owner(q: CallbackQuery, locale: str | None, admin_id: int) -> bool:
    """Re-check Owner rank right before an irreversible promotion decision.

    The entry check reads ownership alongside the request fetch. A transfer
    across the later awaits must not let a demoted reviewer grant Admin.
    """
    try:
        owner = await db.users_roles.is_owner(admin_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("promo decision owner re-read failed for %d: %s", admin_id, exc)
        await answer_alert(q, t("admins.error.role_lookup_failed", locale, plain=True))
        return False
    if not owner:
        await answer_alert(q, replies.perm_owner_only(locale, plain=True))
    return bool(owner)


async def execute_promo_decision(ctx: Ctx) -> None:
    """Handle approve / reject decisions on promotion request cards.

    Owner-only callback. Answers the query and fetches the request record in
    parallel. On approve, executes ``Promote.execute`` and updates the card. On
    reject, marks the request resolved and edits the card to show the rejection.
    """
    q = ctx.callback_query
    if q is None:
        return
    data = callback_text_of(q)
    if not data:
        await q.answer()
        return
    admin = ctx.effective_user
    if admin is None:
        await q.answer()
        return
    try:
        action, request_id = data.split(":", 1)
    except ValueError:
        await q.answer()
        return
    # * request_id is known from data, so the record fetch fires
    # * speculatively alongside the ownership check. The locale resolves in
    # * the same batch so one resolution per handler keeps the catalog off the
    # * critical path. The query is answered per branch, never here: Telegram
    # * accepts one answer, so an early ack would swallow every alert below.
    locale, is_owner, req_result = await asyncio.gather(
        locale_for_update(ctx),
        db.users_roles.is_owner(admin.id, fresh=True),
        db.queues_db.get_request_by_id(request_id),
        return_exceptions=True,
    )
    throw_if_cancelled((locale, is_owner, req_result))
    if isinstance(locale, BaseException):
        locale = None
    if isinstance(is_owner, BaseException):
        log.warning("promote_decision owner check failed: %s", is_owner)
        # * The card is shared, so a refused tap must leave its buttons in
        # * place: an edit would let any reader destroy the Owner's only
        # * decision surface.
        await answer_alert(q, t("admins.error.role_lookup_failed", locale, plain=True))
        return
    if not is_owner:
        await answer_alert(q, replies.perm_owner_only(locale, plain=True))
        return
    if isinstance(req_result, BaseException):
        log.error("get_request_by_id failed for %s: %s", request_id, req_result)
        await answer_ack(q)
        await safe_edit_cb(
            q,
            t("admins.error.request_not_found", locale, plain=True),
            parse_mode=None,
            log_level="debug",
            log_label="promote_decision db-error",
            catch_all=True,
        )
        return
    if not req_result:
        await answer_ack(q)
        await safe_edit_cb(
            q,
            t("admins.error.request_not_found", locale, plain=True),
            parse_mode=None,
            log_level="debug",
            log_label="promote_decision not-found",
            catch_all=True,
        )
        return
    req = req_result
    # * A concurrent tap may have resolved the request after our fetch.
    if req.get("status") != "pending":
        await answer_ack(q)
        await cb_error_edit(
            q,
            t("admins.error.request_not_found", locale, plain=True),
            log_label="promote_decision resolved",
            parse_mode=None,
        )
        return
    target_id = req.get("target_user_id", 0)
    target_fname = req.get("first_name", str(target_id))

    if action == "promo_approve":
        # * A request can outlive an ownership transfer. Approving it would
        # * rewrite the owner assignment as Admin, so the Owner role is
        # * refused here and the request stays pending.
        try:
            target_role = await db.users_roles.get_effective_role(target_id, fresh=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("promo_approve target role lookup failed for %d", target_id)
            await answer_alert(
                q, t("admins.error.role_lookup_failed", locale, plain=True)
            )
            return
        if target_role == "owner":
            await answer_alert(
                q, t("admins.promote.target_is_owner", locale, plain=True)
            )
            return
        # * A banned target must not gain rank through a queued request.
        ban_refusal = await banned_target_refusal(
            target_id, locale, log_label="promo_approve ban-guard"
        )
        if ban_refusal is not None:
            await answer_ack(q)
            await cb_error_edit(
                q,
                ban_refusal,
                log_label="promo_approve banned-target",
                parse_mode=None,
            )
            return
        if not await _still_owner(q, locale, admin.id):
            return
        # * Resolve-first claim, then grant: the atomic resolve decides a
        # * concurrent approve/reject race before any privilege is written.
        try:
            db_resolve_r = await db.queues_db.resolve(request_id, "approved", admin.id)
        except Exception:
            log.exception("resolve(approved) failed for request %s", request_id)
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("admins.decision.approve_fail", locale, plain=True),
                log_label="promo_approve db-fail",
                parse_mode=None,
            )
            return
        if db_resolve_r is False:
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("admins.error.request_not_found", locale, plain=True),
                log_label="promo_approve already-resolved",
                parse_mode=None,
            )
            return
        try:
            await db.users_roles.add_admin(target_id, admin.id)
        except Exception:
            log.exception(
                "add_admin failed for %d (request %s, already resolved)",
                target_id,
                request_id,
            )
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("admins.decision.approve_fail", locale, plain=True),
                log_label="promo_approve db-fail",
                parse_mode=None,
            )
            return
        await answer_ack(q)
        # * The assignment already revoked the previous role in the same
        # * transaction; a second revocation would strip the new admin role.
        cleanup_r = await asyncio.gather(
            db.users_cache.upsert_user(target_id, None, target_fname),
            return_exceptions=True,
        )
        for _r in cleanup_r:
            if isinstance(_r, asyncio.CancelledError):
                raise _r
            if isinstance(_r, BaseException):
                log.warning(
                    "promo_approve cleanup failed for target=%d: %s", target_id, _r
                )
        log_text = promote_approved_log(
            target_id,
            target_fname,
            admin.id,
            display_name(admin),
            request_id,
        )
        card_text = getattr(q.message, "text", "") if q.message is not None else ""
        if not card_text:
            card_text = promote_request_log(
                target_id, target_fname, req.get("username"), request_id
            )
        decision_text = card_text + t(
            "admins.decision.approved_suffix", locale, name=display_name(admin)
        )
        target_locale = await locale_for_user(target_id)
        notify_results = await asyncio.gather(
            safe_edit_cb(q, decision_text, reply_markup=None),
            send_text(
                ctx.bot,
                target_id,
                t(
                    "admins.decision.approve_dm",
                    target_locale,
                    community=cfg.community_name,
                    plain=True,
                ),
            ),
            send_log(ctx.bot, log_text),
            return_exceptions=True,
        )
        throw_if_cancelled(notify_results)
        for i, r in enumerate(notify_results):
            if isinstance(r, BaseException):
                log.debug("promo_approve notify[%d] failed: %s", i, r)

    elif action == "promo_reject":
        if not await _still_owner(q, locale, admin.id):
            return
        # * Resolve first and atomically: only the winner may mutate the UI.
        try:
            resolved = await db.queues_db.resolve(request_id, "rejected", admin.id)
        except Exception:
            log.exception("resolve(rejected) failed for request %s", request_id)
            resolved = False
        if not resolved:
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("admins.decision.reject_fail", locale, plain=True),
                log_label="promo_reject db-fail",
                parse_mode=None,
            )
            return
        await answer_ack(q)
        log_text = promote_rejected_log(
            target_id,
            target_fname,
            admin.id,
            display_name(admin),
            request_id,
        )
        card_text = getattr(q.message, "text", "") if q.message is not None else ""
        if not card_text:
            card_text = promote_request_log(
                target_id, target_fname, req.get("username"), request_id
            )
        decision_text = card_text + t(
            "admins.decision.rejected_suffix", locale, name=display_name(admin)
        )
        target_locale = await locale_for_user(target_id)
        reject_results = await asyncio.gather(
            safe_edit_cb(q, decision_text, reply_markup=None),
            send_text(
                ctx.bot,
                target_id,
                t("admins.decision.reject_dm", target_locale, plain=True),
            ),
            send_log(ctx.bot, log_text),
            return_exceptions=True,
        )
        throw_if_cancelled(reject_results)
        for i, r in enumerate(reject_results):
            if isinstance(r, BaseException):
                log.debug("promo_reject notify[%d] failed: %s", i, r)
