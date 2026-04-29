# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Transsion Core owner and admin management with promotion request workflow."""
import logging
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import BRANDING
from ..database import promotion_requests, tc_admins, tc_owners
from ..utils.auth import get_owner_id, is_authorized, is_tc_owner
from ..utils.format import fmt_now, safe_first_name, user_link, utcnow
from ..utils.logger import log_to_channel
from ..utils.targets import resolve_target

logger = logging.getLogger(__name__)


async def cmd_promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Promote a user: owner promotes immediately; admin creates a request."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_authorized(user.id):
        await msg.reply_text("You are not authorized.")
        return

    if not (context.args or (msg.reply_to_message and msg.reply_to_message.from_user)):
        await msg.reply_text(
            "Reply to a user, provide a user ID, or provide a username to promote."
        )
        return

    target = await resolve_target(update, context)
    if target is None:
        await msg.reply_text("Cannot resolve user.")
        return

    if target.id == user.id:
        await msg.reply_text("You cannot promote yourself.")
        return

    if await tc_owners.find_one({"user_id": target.id}):
        await msg.reply_text("Already a Transsion Core Admin.")
        return

    if await tc_admins.find_one({"user_id": target.id}):
        await msg.reply_text("Already a Transsion Core Admin.")
        return

    sender_is_owner = await is_tc_owner(user.id)

    if sender_is_owner:
        await tc_admins.insert_one(
            {"user_id": target.id, "promoted_by": user.id, "promoted_date": utcnow()}
        )
        await msg.reply_text(f"User {target.id} is now a Transsion Core Admin.")
        await log_to_channel(
            context,
            "<b>New Transsion Core Admin Promoted</b>\n"
            f"{BRANDING}\n"
            f"Admin: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
            f"Promoted by Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
            f"Date: {fmt_now()}",
        )
        return

    # Sender is a TC admin: create a promotion request for owner approval.
    request_id = str(uuid.uuid4())
    await promotion_requests.insert_one(
        {
            "request_id": request_id,
            "target_id": target.id,
            "promoted_by": user.id,
            "status": "pending",
            "requested_date": utcnow(),
            "resolved_date": None,
            "resolved_by": None,
        }
    )
    await msg.reply_text(
        f"Promotion request for {target.id} has been sent to the "
        "Transsion Core Owner for approval."
    )

    owner_id = await get_owner_id()
    notification_text = (
        "<b>New Promotion Request</b>\n"
        f"{BRANDING}\n"
        f"Requested by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Target: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
        f"Request ID: {request_id}\n"
        f"Date: {fmt_now()}"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=f"approve_promote_{request_id}"
                ),
                InlineKeyboardButton(
                    "Reject", callback_data=f"reject_promote_{request_id}"
                ),
            ]
        ]
    )

    sent_to_owner = False
    if owner_id:
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=notification_text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
            sent_to_owner = True
        except TelegramError:
            pass

    if not sent_to_owner:
        owner_mention = (
            user_link(owner_id, str(owner_id)) if owner_id else "Owner"
        )
        await log_to_channel(
            context,
            notification_text + f"\n\nNote: Could not reach owner {owner_mention} via PM.",
            reply_markup=kb,
        )

    await log_to_channel(
        context,
        "<b>Promotion Request Sent</b>\n"
        f"{BRANDING}\n"
        f"Requested by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Target: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
        f"Date: {fmt_now()}",
    )


async def on_promote_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle approve/reject callbacks for promotion requests."""
    cq = update.callback_query
    if cq is None or getattr(cq, "from_user", None) is None or getattr(cq, "data", None) is None:
        return

    data = getattr(cq, "data", None)
    if data is None:
        return
    data_str = str(data)
    if data_str.startswith("approve_promote_"):
        decision = "approve"
        request_id = data_str[len("approve_promote_"):]
    elif data_str.startswith("reject_promote_"):
        decision = "reject"
        request_id = data_str[len("reject_promote_"):]
    else:
        return

    reviewer = cq.from_user
    if not await is_tc_owner(reviewer.id):
        await cq.answer("Only the Transsion Core Owner can act on this.", show_alert=True)
        return

    record = await promotion_requests.find_one({"request_id": request_id})
    if not record:
        await cq.answer("Promotion request not found.", show_alert=True)
        return

    if record.get("status") != "pending":
        await cq.answer("This request has already been resolved.", show_alert=True)
        return

    await cq.answer()
    now = utcnow()

    if decision == "approve":
        target_id = record["target_id"]
        if not await tc_admins.find_one({"user_id": target_id}):
            await tc_admins.insert_one(
                {
                    "user_id": target_id,
                    "promoted_by": reviewer.id,
                    "promoted_date": now,
                }
            )
        await promotion_requests.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": "approved",
                    "resolved_date": now,
                    "resolved_by": reviewer.id,
                }
            },
        )
        try:
            target_chat = await context.bot.get_chat(target_id)
            target_name = target_chat.first_name or str(target_id)
        except TelegramError:
            target_name = str(target_id)

        try:
            await cq.edit_message_text(
                f"Promotion request approved. {target_name} is now a Transsion Core Admin.",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

        await log_to_channel(
            context,
            "<b>New Transsion Core Admin Promoted</b>\n"
            f"{BRANDING}\n"
            f"Admin: {user_link(target_id, target_name)} (ID: {target_id})\n"
            f"Promoted by Owner: {user_link(reviewer.id, safe_first_name(reviewer))} (ID: {reviewer.id})\n"
            f"Date: {fmt_now()}",
        )
    else:
        await promotion_requests.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": "rejected",
                    "resolved_date": now,
                    "resolved_by": reviewer.id,
                }
            },
        )
        try:
            await cq.edit_message_text("Promotion request rejected.")
        except TelegramError:
            pass

        await log_to_channel(
            context,
            "<b>Promotion Request Rejected</b>\n"
            f"{BRANDING}\n"
            f"Rejected by Owner: {user_link(reviewer.id, safe_first_name(reviewer))} (ID: {reviewer.id})\n"
            f"Request ID: {request_id}\n"
            f"Date: {fmt_now()}",
        )


async def cmd_demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Demote a TC admin. Owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_tc_owner(user.id):
        await msg.reply_text("You are not authorized.")
        return

    if not (context.args or (msg.reply_to_message and msg.reply_to_message.from_user)):
        await msg.reply_text(
            "Reply to a user, provide a user ID, or provide a username to demote."
        )
        return

    target = await resolve_target(update, context)
    if target is None:
        await msg.reply_text("Cannot resolve user.")
        return

    if target.id == user.id:
        await msg.reply_text(
            "I cannot demote myself. I hold a crucial position in this "
            "Transsion Core. Please ask the owner to do it."
        )
        return

    if await tc_owners.find_one({"user_id": target.id}):
        await msg.reply_text("Cannot demote the Transsion Core Owner.")
        return

    res = await tc_admins.delete_one({"user_id": target.id})
    if res.deleted_count == 0:
        await msg.reply_text("Not a Transsion Core Admin.")
        return

    await msg.reply_text("User demoted from Transsion Core Admin.")
    await log_to_channel(
        context,
        "<b>Transsion Core Admin Demoted</b>\n"
        f"{BRANDING}\n"
        f"Admin: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
        f"Demoted by Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Date: {fmt_now()}",
    )


async def cmd_transfer_owner(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Transfer TC ownership to another user. Owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_tc_owner(user.id):
        await msg.reply_text("Only the owner can use this command.")
        return

    if not (context.args or (msg.reply_to_message and msg.reply_to_message.from_user)):
        await msg.reply_text(
            "Reply to a user, provide a user ID, or provide a username "
            "to transfer ownership to."
        )
        return

    target = await resolve_target(update, context)
    if target is None:
        await msg.reply_text("Cannot resolve user.")
        return

    if target.id == user.id:
        await msg.reply_text("You are already the owner.")
        return

    await tc_owners.delete_many({})
    await tc_owners.insert_one({"user_id": target.id})
    await tc_admins.delete_one({"user_id": target.id})
    await tc_admins.update_one(
        {"user_id": user.id},
        {
            "$setOnInsert": {
                "user_id": user.id,
                "promoted_by": user.id,
                "promoted_date": utcnow(),
            }
        },
        upsert=True,
    )

    await msg.reply_text(f"Ownership transferred to {target.id}.")
    await log_to_channel(
        context,
        "<b>Transsion Core Ownership Transferred</b>\n"
        f"{BRANDING}\n"
        f"New Owner: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
        f"Previous Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Date: {fmt_now()}",
    )


async def cmd_promo_requests(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """List all pending promotion requests. Owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_tc_owner(user.id):
        await msg.reply_text("You are not authorized.")
        return

    cursor = promotion_requests.find({"status": "pending"})
    pending = [r async for r in cursor]

    if not pending:
        await msg.reply_text("No pending promotion requests.")
        return

    for req in pending:
        request_id = req["request_id"]
        target_id = req["target_id"]
        promoted_by = req["promoted_by"]
        requested_date = req.get("requested_date")

        try:
            target_chat = await context.bot.get_chat(target_id)
            target_name = target_chat.first_name or str(target_id)
        except TelegramError:
            target_name = str(target_id)

        try:
            req_by_chat = await context.bot.get_chat(promoted_by)
            req_by_name = req_by_chat.first_name or str(promoted_by)
        except TelegramError:
            req_by_name = str(promoted_by)

        from ..utils.format import fmt_dt
        date_str = fmt_dt(requested_date) if requested_date else "Unknown"
        text = (
            "<b>Pending Promotion Request</b>\n"
            f"Target: {user_link(target_id, target_name)} (ID: {target_id})\n"
            f"Requested by: {user_link(promoted_by, req_by_name)} (ID: {promoted_by})\n"
            f"Date: {date_str}\n"
            f"Request ID: {request_id}"
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Approve", callback_data=f"approve_promote_{request_id}"
                    ),
                    InlineKeyboardButton(
                        "Reject", callback_data=f"reject_promote_{request_id}"
                    ),
                ]
            ]
        )
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
