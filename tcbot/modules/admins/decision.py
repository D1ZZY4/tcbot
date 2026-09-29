# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Approve / reject decisions on promotion request cards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.admins.shared import _RL_CMD_LIMIT, _RL_PERIOD_S
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.parse_logmsg import (
    promote_approved_log,
    promote_rejected_log,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import esc
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promo_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve / reject decisions on promotion request cards.

    Owner-only callback. Answers the query and fetches the request record in
    parallel. On approve, executes ``Promote.execute`` and updates the card. On
    reject, marks the request resolved and edits the card to show the rejection.
    """
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    admin = update.effective_user
    if admin is None:
        await q.answer()
        return
    try:
        action, request_id = q.data.split(":", 1)
    except ValueError:
        await q.answer()
        return
    # * request_id is known from q.data, so the record fetch fires
    # * speculatively alongside the ownership check and q.answer().
    is_owner, req_result, answer_r = await asyncio.gather(
        db.users_roles.is_owner(admin.id),
        db.queues_db.get_request_by_id(request_id),
        q.answer(),
        return_exceptions=True,
    )
    throw_if_cancelled((is_owner, req_result, answer_r))
    if isinstance(answer_r, BaseException):
        log.debug("on_promo_decision answer failed: %s", answer_r)
    if isinstance(is_owner, BaseException):
        log.warning("on_promo_decision owner check failed: %s", is_owner)
        try:
            await q.edit_message_text(
                t(
                    "admins.error.role_lookup_failed",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_promo_decision lookup-fail edit failed: %s", exc)
        return
    if not is_owner:
        try:
            await q.edit_message_text(
                replies.perm_founder_only(await locale_for_update(update), plain=True)
            )
        except Exception as exc:
            log.debug("on_promo_decision perm-denied edit failed: %s", exc)
        return
    if isinstance(req_result, BaseException):
        log.error("get_request_by_id failed for %s: %s", request_id, req_result)
        try:
            await q.edit_message_text(
                t(
                    "admins.error.request_not_found",
                    await locale_for_update(update),
                    plain=True,
                )
            )
        except Exception as exc:
            log.debug("on_promo_decision db-error edit failed: %s", exc)
        return
    if not req_result:
        try:
            await q.edit_message_text(
                t(
                    "admins.error.request_not_found",
                    await locale_for_update(update),
                    plain=True,
                )
            )
        except Exception as exc:
            log.debug("on_promo_decision not-found edit failed: %s", exc)
        return
    req = req_result
    # * A concurrent tap may have resolved the request after our fetch.
    # * resolve() below is atomic, but refuse early so a stale card never
    # * shows a second success message.
    if req.get("status") != "pending":
        try:
            await q.edit_message_text(
                t(
                    "admins.error.request_not_found",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_promo_decision resolved edit failed: %s", exc)
        return
    target_id = req.get("target_id", 0)
    target_fname = req.get("first_name", str(target_id))
    lc, lt = cfg.logs

    if action == "promo_approve":
        # * Sequential, not parallel: add_admin first so a failure leaves
        # * the request pending and retryable. The old parallel form could
        # * resolve "approved" while add_admin failed, orphaning the user.
        # * add_admin is an idempotent upsert, so a retry after a resolve
        # * failure still converges; the atomic resolve decides a race.
        try:
            await db.users_roles.add_admin(target_id, admin.id)
        except Exception:
            log.exception(
                "add_admin failed for %d (request %s)",
                target_id,
                request_id,
            )
            try:
                await q.edit_message_text(
                    t(
                        "admins.decision.approve_fail",
                        await locale_for_update(update),
                        plain=True,
                    ),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("promo_approve db-fail edit failed: %s", exc)
            return
        try:
            db_resolve_r = await db.queues_db.resolve(request_id, "approved", admin.id)
        except Exception:
            log.exception("resolve(approved) failed for request %s", request_id)
            try:
                await q.edit_message_text(
                    t(
                        "admins.decision.approve_fail",
                        await locale_for_update(update),
                        plain=True,
                    ),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("promo_approve db-fail edit failed: %s", exc)
            return
        if db_resolve_r is False:
            try:
                await q.edit_message_text(
                    t(
                        "admins.decision.approve_fail",
                        await locale_for_update(update),
                        plain=True,
                    ),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("promo_approve db-fail edit failed: %s", exc)
            return
        # * A Developer/Tester row left beside the new Admin record
        # * resurrects on the next demote, so clean up best-effort; the
        # * promotion already committed, so failures only log.
        cleanup_r = await asyncio.gather(
            db.users_roles.remove_role(target_id),
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
            admin.first_name,
            request_id,
        )
        existing_text = ""
        if q.message is not None:
            # * Plain .text: the edit sends MarkdownV2, so the display text
            # * is re-escaped here. Empty on MaybeInaccessibleMessage.
            existing_text = esc(getattr(q.message, "text", "") or "")
        locale, target_locale = await asyncio.gather(
            locale_for_update(update),
            locale_for_user(target_id),
        )
        notify_results = await asyncio.gather(
            q.edit_message_text(
                existing_text
                + t(
                    "admins.decision.approved_suffix",
                    locale,
                    name=admin.first_name,
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            ),
            ctx.bot.send_message(
                target_id,
                t(
                    "admins.decision.approve_dm",
                    target_locale,
                    community=cfg.community_name,
                    plain=True,
                ),
            ),
            ctx.bot.send_message(
                lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
            ),
            return_exceptions=True,
        )
        for i, r in enumerate(notify_results):
            if isinstance(r, BaseException):
                log.debug("promo_approve notify[%d] failed: %s", i, r)

    elif action == "promo_reject":
        # * Resolve first and atomically: only the winner may mutate the UI,
        # * so a lost race shows an error instead of a "Rejected" card over
        # * a still-pending request.
        try:
            resolved = await db.queues_db.resolve(request_id, "rejected", admin.id)
        except Exception:
            log.exception("resolve(rejected) failed for request %s", request_id)
            resolved = False
        if not resolved:
            try:
                await q.edit_message_text(
                    t(
                        "admins.decision.reject_fail",
                        await locale_for_update(update),
                        plain=True,
                    ),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("promo_reject db-fail edit failed: %s", exc)
            return
        log_text = promote_rejected_log(
            target_id,
            target_fname,
            admin.id,
            admin.first_name,
            request_id,
        )
        existing_text = ""
        if q.message is not None:
            existing_text = esc(getattr(q.message, "text", "") or "")
        locale, target_locale = await asyncio.gather(
            locale_for_update(update),
            locale_for_user(target_id),
        )
        reject_results = await asyncio.gather(
            q.edit_message_text(
                existing_text
                + t(
                    "admins.decision.rejected_suffix",
                    locale,
                    name=admin.first_name,
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            ),
            ctx.bot.send_message(
                target_id,
                t("admins.decision.reject_dm", target_locale, plain=True),
            ),
            ctx.bot.send_message(
                lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
            ),
            return_exceptions=True,
        )
        for i, r in enumerate(reject_results):
            if isinstance(r, BaseException):
                log.debug("promo_reject notify[%d] failed: %s", i, r)
