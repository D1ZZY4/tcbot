"""Appeal flow: deep link, instructions, submission, admin review."""
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import (
    APPEAL_DISCUSSION_TOPIC,
    APPEAL_INSTRUCTION_TEMPLATE,
    APPEAL_TOPIC,
    BRANDING,
    LOG_CHANNEL,
    MAIN_GROUP,
)
from ..db import bans
from ..utils.auth import is_authorized
from ..utils.format import (
    chat_id_to_link_id,
    fmt_dt,
    fmt_now,
    safe_first_name,
    topic_link,
    user_link,
    utcnow,
)
from ..utils.logger import log_to_channel

logger = logging.getLogger(__name__)


def _get_sessions(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("appeal_sessions", {})


def _get_reviews(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("appeal_reviews", {})


async def start_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE, ban_id: str) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    if msg.chat.type != ChatType.PRIVATE:
        await msg.reply_text("Appeals can only be started in a private chat with the bot.")
        return

    record = await bans.find_one({"ban_id": ban_id})
    if not record or not record.get("is_active"):
        await msg.reply_text("Invalid or expired ban.")
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Cancel", callback_data="cancel_appeal")]]
    )
    instruction = APPEAL_INSTRUCTION_TEMPLATE.format(ban_id=ban_id)
    sent = await msg.reply_text(instruction, reply_markup=keyboard, disable_web_page_preview=True)

    sessions = _get_sessions(context)
    sessions[user.id] = {
        "ban_id": ban_id,
        "log_message_id": record["log_message_id"],
        "instruction_msg_id": sent.message_id,
        "chat_id": msg.chat.id,
    }


async def on_cancel_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None or cq.from_user is None:
        return
    sessions = _get_sessions(context)
    sess = sessions.pop(cq.from_user.id, None)
    await cq.answer()
    try:
        await cq.edit_message_text("Appeal cancelled.")
    except TelegramError:
        pass


async def on_appeal_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    if msg.chat.type != ChatType.PRIVATE:
        return

    sessions = _get_sessions(context)
    sess = sessions.get(user.id)
    if sess is None:
        return

    text = msg.text or ""
    if not text.lstrip().lower().startswith("#appeal"):
        return

    log_message_id = sess["log_message_id"]
    # Require the log link to contain the stored log_message_id as a
    # standalone path segment (so e.g. id 123 does not match 1234567).
    import re as _re
    if not _re.search(rf"/{log_message_id}(?:[^0-9]|$)", text):
        await msg.reply_text("Invalid log link. Please check and try again.")
        return

    try:
        appeal_msg = await context.bot.send_message(
            chat_id=MAIN_GROUP,
            message_thread_id=APPEAL_TOPIC,
            text=text,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.exception("Failed to post appeal: %s", exc)
        await msg.reply_text("Failed to submit appeal. Please try again later.")
        return

    appeal_link = topic_link(MAIN_GROUP, appeal_msg.message_id, APPEAL_TOPIC)
    ban_id = sess["ban_id"]
    submitted_at = utcnow()

    review_text = (
        "<b>New Appeal Request</b>\n"
        f"User: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Ban ID: {ban_id}\n"
        f'Appeal: <a href="{appeal_link}">View</a>\n'
        f"Submitted: {fmt_dt(submitted_at)}\n\n"
        "This appeal is pending review."
    )
    review_kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"appeal_approve_{ban_id}"),
                InlineKeyboardButton("Reject", callback_data=f"appeal_reject_{ban_id}"),
            ]
        ]
    )

    try:
        review_msg = await context.bot.send_message(
            chat_id=MAIN_GROUP,
            message_thread_id=APPEAL_DISCUSSION_TOPIC,
            text=review_text,
            parse_mode=ParseMode.HTML,
            reply_markup=review_kb,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.exception("Failed to send review msg: %s", exc)
        await msg.reply_text("Failed to submit appeal. Please try again later.")
        return

    record = await bans.find_one({"ban_id": ban_id})
    reviews = _get_reviews(context)
    reviews[ban_id] = {
        "review_message_id": review_msg.message_id,
        "submitted_at": submitted_at,
        "ban_admin_id": record["admin_user_id"] if record else None,
        "user_id": user.id,
        "user_first_name": safe_first_name(user),
    }

    try:
        await context.bot.edit_message_text(
            chat_id=sess["chat_id"],
            message_id=sess["instruction_msg_id"],
            text="Your appeal has been submitted. Federation admins will review it.",
        )
    except TelegramError:
        pass

    sessions.pop(user.id, None)

    await log_to_channel(
        context,
        "<b>New Appeal Submitted</b>\n"
        f"{BRANDING}\n"
        f"User: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Ban ID: {ban_id}\n"
        f'Appeal: <a href="{appeal_link}">View</a>\n'
        f"Date: {fmt_dt(submitted_at)}",
    )


async def on_appeal_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None or cq.from_user is None or cq.data is None:
        return

    data = cq.data
    if data.startswith("appeal_approve_"):
        decision = "approve"
        ban_id = data[len("appeal_approve_"):]
    elif data.startswith("appeal_reject_"):
        decision = "reject"
        ban_id = data[len("appeal_reject_"):]
    else:
        return

    user = cq.from_user
    if not await is_authorized(user.id):
        await cq.answer("You are not authorized.", show_alert=True)
        return

    record = await bans.find_one({"ban_id": ban_id})
    reviews = _get_reviews(context)
    review = reviews.get(ban_id)

    if not record or not record.get("is_active"):
        await cq.answer("This ban is already inactive.", show_alert=True)
        try:
            await cq.edit_message_text("Appeal resolved (ban no longer active).")
        except TelegramError:
            pass
        if review:
            reviews.pop(ban_id, None)
        return

    if review:
        elapsed = (utcnow() - review["submitted_at"]).total_seconds()
        if elapsed < 12 * 3600 and review["ban_admin_id"] is not None:
            if user.id != review["ban_admin_id"]:
                await cq.answer(
                    "Only the banning admin can review within the first 12 hours.",
                    show_alert=True,
                )
                return

    await cq.answer()
    user_id_appellant = review["user_id"] if review else record["banned_user_id"]
    user_first_name_appellant = (
        review["user_first_name"] if review else str(user_id_appellant)
    )

    if decision == "approve":
        await bans.update_one({"ban_id": ban_id}, {"$set": {"is_active": False}})
        try:
            await cq.edit_message_text(
                f"Appeal approved by {user_link(user.id, safe_first_name(user))}. "
                "User has been unbanned.",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        await log_to_channel(
            context,
            "<b>Appeal Approved</b>\n"
            f"{BRANDING}\n"
            f"User: {user_link(user_id_appellant, user_first_name_appellant)} (ID: {user_id_appellant})\n"
            f"Ban ID: {ban_id}\n"
            f"Approved by: {user_link(user.id, safe_first_name(user))}\n"
            f"Date: {fmt_now()}",
        )
        try:
            await context.bot.send_message(
                chat_id=user_id_appellant,
                text="Your appeal has been approved. You have been unbanned from the TCF federation.",
            )
        except TelegramError:
            pass
    else:
        try:
            await cq.edit_message_text(
                f"Appeal rejected by {user_link(user.id, safe_first_name(user))}.",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        await log_to_channel(
            context,
            "<b>Appeal Rejected</b>\n"
            f"{BRANDING}\n"
            f"User: {user_link(user_id_appellant, user_first_name_appellant)} (ID: {user_id_appellant})\n"
            f"Ban ID: {ban_id}\n"
            f"Rejected by: {user_link(user.id, safe_first_name(user))}\n"
            f"Date: {fmt_now()}",
        )
        try:
            await context.bot.send_message(
                chat_id=user_id_appellant,
                text="Your appeal has been rejected. The ban remains in effect.",
            )
        except TelegramError:
            pass

    reviews.pop(ban_id, None)
