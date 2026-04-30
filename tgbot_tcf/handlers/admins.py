# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Owner / admin role-management handlers (PROMPT Features 9, 10, 11, 14).

Thin Telegram entry points: validate the update, route the work to
:mod:`tgbot_tcf.modules.admins_mod`, then reply / log using the centralised
templates in :mod:`tgbot_tcf.modules.messages` and
:mod:`tgbot_tcf.modules.log_templates`.
"""
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import admins_repo
from ..modules import admins_mod, keyboards, log_templates
from ..modules.messages import M
from ..utils.format import fmt_dt, safe_first_name, user_link
from ..utils.logger import log_to_channel
from ..utils.users import resolve_identity
from .helper import auth, messaging, targets

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- /tcpromote

async def cmd_promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner promotes immediately; admin creates a request for owner approval."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    if not (
        context.args
        or (msg.reply_to_message and msg.reply_to_message.from_user)
    ):
        await msg.reply_text(M.PROMOTE_NEEDS_TARGET)
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    if target.id == user.id:
        await msg.reply_text(M.PROMOTE_SELF_BLOCKED)
        return

    if await admins_repo.is_owner(target.id) or await admins_repo.is_admin(target.id):
        await msg.reply_text(M.ALREADY_TC_ADMIN)
        return

    if await auth.is_owner(user.id):
        await admins_mod.promote_immediately(target_id=target.id, by_owner_id=user.id)
        await msg.reply_text(M.PROMOTE_OWNER_DONE.format(target_id=target.id))
        await log_to_channel(
            context,
            log_templates.admin_promoted(
                target_id=target.id,
                target_name=target.first_name,
                promoted_by_id=user.id,
                promoted_by_name=safe_first_name(user),
            ),
        )
        return

    # TC admin: create a request and notify the owner.
    request_id = await admins_mod.create_promotion_request(
        target_id=target.id, requested_by=user.id
    )
    await msg.reply_text(M.PROMOTION_REQUEST_SENT.format(target_id=target.id))

    notification = log_templates.promotion_request_notification(
        request_id=request_id,
        requested_by_id=user.id,
        requested_by_name=safe_first_name(user),
        target_id=target.id,
        target_name=target.first_name,
    )
    review_kb = keyboards.promotion_request(request_id)

    owner_id = await admins_repo.get_owner_id()
    delivered = False
    if owner_id is not None:
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=notification,
                parse_mode=ParseMode.HTML,
                reply_markup=review_kb,
                disable_web_page_preview=True,
            )
            delivered = True
        except TelegramError:
            pass

    if not delivered:
        owner_mention = (
            user_link(owner_id, str(owner_id)) if owner_id else "Owner"
        )
        await log_to_channel(
            context,
            notification + f"\n\nNote: Could not reach owner {owner_mention} via PM.",
            reply_markup=review_kb,
        )

    await log_to_channel(
        context,
        log_templates.promotion_request_sent(
            requested_by_id=user.id,
            requested_by_name=safe_first_name(user),
            target_id=target.id,
            target_name=target.first_name,
        ),
    )


# ----------------------------------------------------- promotion-request review

async def on_promote_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Approve / Reject button on a promotion-request notification."""
    cq = update.callback_query
    if (
        cq is None
        or getattr(cq, "from_user", None) is None
        or getattr(cq, "data", None) is None
    ):
        return

    data = str(cq.data)
    if data.startswith("approve_promote_"):
        decision = "approve"
        request_id = data[len("approve_promote_"):]
    elif data.startswith("reject_promote_"):
        decision = "reject"
        request_id = data[len("reject_promote_"):]
    else:
        return

    reviewer = cq.from_user
    if not await auth.is_owner(reviewer.id):
        await cq.answer(M.PROMOTION_OWNER_ONLY_ALERT, show_alert=True)
        return

    record = await admins_mod.fetch_request(request_id)
    if record is None:
        await cq.answer(M.PROMOTION_REQUEST_NOT_FOUND_ALERT, show_alert=True)
        return
    if record.get("status") != "pending":
        await cq.answer(M.PROMOTION_REQUEST_RESOLVED_ALERT, show_alert=True)
        return

    await cq.answer()

    if decision == "approve":
        record = await admins_mod.approve_request(
            request_id=request_id, by_owner_id=reviewer.id
        )
        if record is None:
            return
        target_id = record["target_id"]
        target_name = (await resolve_identity(context, target_id)).display_name
        await messaging.safe_edit_callback(
            cq,
            M.PROMOTION_REQUEST_APPROVED.format(target_name=target_name),
        )
        await log_to_channel(
            context,
            log_templates.admin_promoted(
                target_id=target_id,
                target_name=target_name,
                promoted_by_id=reviewer.id,
                promoted_by_name=safe_first_name(reviewer),
            ),
        )
    else:
        await admins_mod.reject_request(
            request_id=request_id, by_owner_id=reviewer.id
        )
        await messaging.safe_edit_callback(cq, M.PROMOTION_REQUEST_REJECTED)
        await log_to_channel(
            context,
            log_templates.promotion_request_rejected_log(
                request_id=request_id,
                reviewer_id=reviewer.id,
                reviewer_name=safe_first_name(reviewer),
            ),
        )


# --------------------------------------------------------------- /tcdemote

async def cmd_demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only demotion of a TC admin."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_owner(msg, user.id):
        return

    if not (
        context.args
        or (msg.reply_to_message and msg.reply_to_message.from_user)
    ):
        await msg.reply_text(M.DEMOTE_NEEDS_TARGET)
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    if target.id == user.id:
        await msg.reply_text(M.DEMOTE_SELF_BLOCKED)
        return

    if await admins_repo.is_owner(target.id):
        await msg.reply_text(M.DEMOTE_OWNER_BLOCKED)
        return

    if not await admins_mod.demote_user(target.id):
        await msg.reply_text(M.NOT_TC_ADMIN)
        return

    await msg.reply_text(M.DEMOTE_DONE)
    await log_to_channel(
        context,
        log_templates.admin_demoted(
            target_id=target.id,
            target_name=target.first_name,
            demoted_by_id=user.id,
            demoted_by_name=safe_first_name(user),
        ),
    )


# --------------------------------------------------------- /tctransfer

async def cmd_transfer_owner(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Transfer Transsion Core ownership. Owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_owner_for_transfer(msg, user.id):
        return

    if not (
        context.args
        or (msg.reply_to_message and msg.reply_to_message.from_user)
    ):
        await msg.reply_text(M.TRANSFER_NEEDS_TARGET)
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    if target.id == user.id:
        await msg.reply_text(M.TRANSFER_SELF_OWNER)
        return

    await admins_mod.transfer_ownership(
        new_owner_id=target.id, old_owner_id=user.id
    )
    await msg.reply_text(M.TRANSFER_DONE.format(target_id=target.id))
    await log_to_channel(
        context,
        log_templates.ownership_transferred(
            new_owner_id=target.id,
            new_owner_name=target.first_name,
            old_owner_id=user.id,
            old_owner_name=safe_first_name(user),
        ),
    )


# ----------------------------------------------------- /tcpromoterequests

async def cmd_promo_requests(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Owner-only listing of every pending promotion request."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_owner(msg, user.id):
        return

    pending = await admins_mod.list_pending_requests()
    if not pending:
        await msg.reply_text(M.NO_PENDING_PROMO_REQUESTS)
        return

    for req in pending:
        request_id = req["request_id"]
        target_id = req["target_id"]
        promoted_by = req["promoted_by"]
        requested_date = req.get("requested_date")

        target_name = (await resolve_identity(context, target_id)).display_name
        req_by_name = (await resolve_identity(context, promoted_by)).display_name
        date_str = fmt_dt(requested_date) if requested_date else "Unknown"

        text = (
            "<b>Pending Promotion Request</b>\n"
            f"Target: {user_link(target_id, target_name)} (ID: {target_id})\n"
            f"Requested by: {user_link(promoted_by, req_by_name)} (ID: {promoted_by})\n"
            f"Date: {date_str}\n"
            f"Request ID: {request_id}"
        )
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.promotion_request(request_id),
            disable_web_page_preview=True,
        )
