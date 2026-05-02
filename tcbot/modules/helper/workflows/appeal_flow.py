# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Appeal conversation – entry via /start appeal_<ban_id> deep link, DM only."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import message_link

log = logging.getLogger(__name__)

WAITING_APPEAL = 0

## Thread inside MAIN_GROUP for appeal review messages (admin discussion)
APPEAL_DISCUSSION_TOPIC = 11

_INSTRUCTION_TEXT = (
    "Transsion Core [Group] Ban Appeal\n\n"
    "To submit your appeal, reply with a message starting with <code>#appeal</code>, containing:\n"
    "- <b>Log link:</b> (the link to the ban log from the log channel)\n"
    "- <b>Clarification:</b> (your honest explanation)\n"
    "- <b>Agreement:</b> (your commitment not to repeat the violation)\n\n"
    "<b>Example:</b>\n"
    "<pre>#appeal\n"
    "Log link: https://t.me/TranssionCoreFederationLogs/1\n"
    "Clarification: I spammed unintentionally due to an auto-clicker.\n"
    "Agreement: I will not use any automation tools in the group again.</pre>\n\n"
    "Log Channel: @TranssionCoreFederationLogs"
)


## ---------------------------------------------------------------------------
## Entry point (called from start.py when deep link matches appeal_<ban_id>)
## ---------------------------------------------------------------------------

async def start_appeal(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ban_id: str) -> int:
    msg = update.effective_message
    uid = update.effective_user.id

    if update.effective_chat.type != "private":
        await msg.reply_text("Please start this in my private messages.")
        return ConversationHandler.END

    ban = await db.bans_db.get_ban(ban_id)
    if not ban or not ban.get("is_active"):
        await msg.reply_text("Invalid or expired ban.")
        return ConversationHandler.END

    if ban["banned_user_id"] != uid:
        await msg.reply_text("This appeal link is not for your account.")
        return ConversationHandler.END

    if ban.get("review_message_id"):
        await msg.reply_text("You already have a pending appeal under review.")
        return ConversationHandler.END

    ctx.user_data["appeal_ban_id"] = ban_id
    ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)

    instruction_msg = await msg.reply_text(
        _INSTRUCTION_TEXT,
        parse_mode="HTML",
        reply_markup=keyboards.appeal_cancel_kb(),
    )
    ctx.user_data["appeal_instruction_msg_id"] = instruction_msg.message_id

    return WAITING_APPEAL


## ---------------------------------------------------------------------------
## Deep-link entry point (ConversationHandler entry)
## ---------------------------------------------------------------------------

async def cmd_start_appeal_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.effective_message.text or ""
    m = re.search(r"appeal_(\S+)", text)
    if not m:
        return ConversationHandler.END
    ban_id = m.group(1)
    return await start_appeal(update, ctx, ban_id)


## ---------------------------------------------------------------------------
## Cancel callback
## ---------------------------------------------------------------------------

async def on_appeal_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Appeal cancelled.")
    ctx.user_data.pop("appeal_ban_id", None)
    ctx.user_data.pop("appeal_log_msg_id", None)
    ctx.user_data.pop("appeal_instruction_msg_id", None)
    return ConversationHandler.END


## ---------------------------------------------------------------------------
## #appeal message received
## ---------------------------------------------------------------------------

async def on_appeal_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = (msg.text or "").strip()

    if not text.startswith("#appeal"):
        return WAITING_APPEAL

    ban_id = ctx.user_data.get("appeal_ban_id")
    log_msg_id = ctx.user_data.get("appeal_log_msg_id", 0)

    if not ban_id:
        await msg.reply_text("Session expired. Please start the appeal again.")
        return ConversationHandler.END

    ## Validate log link contains the stored log_message_id
    if log_msg_id:
        if str(log_msg_id) not in text:
            await msg.reply_text(
                "Invalid log link. Please check and try again."
            )
            return WAITING_APPEAL

    uid = update.effective_user.id
    user = update.effective_user

    ## Forward raw appeal to APPEAL_TOPIC (thread 12)
    appeal_chat, appeal_thread = cfg.appeals
    appeal_msg_id: int | None = None
    try:
        fwd = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
        appeal_msg_id = fwd.message_id
    except Exception as exc:
        log.error("Appeal forward failed: %s", exc)

    appeal_link = (
        message_link(appeal_chat, appeal_msg_id, appeal_thread) if appeal_msg_id else ""
    )

    ## Post review card to APPEAL_DISCUSSION_TOPIC (thread 11)
    review_text = parse_logmsg.appeal_received_log(uid, user.first_name, ban_id, appeal_link)
    review_msg_id: int | None = None
    try:
        rv = await ctx.bot.send_message(
            cfg.main_group,
            review_text,
            parse_mode="HTML",
            message_thread_id=APPEAL_DISCUSSION_TOPIC,
            reply_markup=keyboards.appeal_review_kb(ban_id),
        )
        review_msg_id = rv.message_id
    except Exception as exc:
        log.error("Appeal review post failed: %s", exc)

    if review_msg_id:
        await db.bans_db.set_review(ban_id, review_msg_id)

    ## Log to LOG_CHANNEL
    lc, lt = cfg.logs
    try:
        await ctx.bot.send_message(
            lc,
            parse_logmsg.appeal_submitted_log(uid, user.first_name, ban_id, appeal_link),
            parse_mode="HTML",
            message_thread_id=lt,
        )
    except Exception as exc:
        log.error("Appeal log failed: %s", exc)

    ## Edit instruction message
    instr_mid = ctx.user_data.get("appeal_instruction_msg_id")
    if instr_mid:
        try:
            await ctx.bot.edit_message_text(
                "Your appeal has been submitted. Transsion Core admins will review it.",
                chat_id=update.effective_chat.id,
                message_id=instr_mid,
            )
        except Exception:
            pass

    ## Cache user
    await db.users_db.upsert_user(uid, user.username, user.first_name, user.last_name)

    return ConversationHandler.END


## ---------------------------------------------------------------------------
## Appeal decision callback (admin presses Approve / Reject in thread 11)
## ---------------------------------------------------------------------------

async def on_appeal_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    admin = update.effective_user

    if not await db.admins_db.is_staff(admin.id):
        await q.answer("You are not authorized.", show_alert=True)
        return

    ## Callback data: appeal_approve_<ban_id> or appeal_reject_<ban_id>
    data = q.data
    if data.startswith("appeal_approve_"):
        action = "approve"
        ban_id = data[len("appeal_approve_"):]
    elif data.startswith("appeal_reject_"):
        action = "reject"
        ban_id = data[len("appeal_reject_"):]
    else:
        await q.answer()
        return

    await q.answer()

    ban = await db.bans_db.get_ban(ban_id)
    if not ban:
        await q.edit_message_text("Ban record not found.", reply_markup=None)
        return

    if not ban.get("is_active"):
        await q.edit_message_text("Appeal resolved (ban no longer active).", reply_markup=None)
        return

    ## 12-hour window: only original banning admin may decide
    review_ts = ban.get("review_timestamp")
    if review_ts:
        elapsed = datetime.now(timezone.utc) - review_ts.replace(tzinfo=timezone.utc)
        if elapsed < timedelta(hours=12):
            if admin.id != ban.get("admin_user_id"):
                await q.answer(
                    "Only the banning admin can review within the first 12 hours.",
                    show_alert=True,
                )
                return

    target_id = ban["banned_user_id"]
    target_fname = await db.users_db.get_first_name(target_id, str(target_id))
    lc, lt = cfg.logs

    if action == "approve":
        await db.bans_db.deactivate_ban(ban_id)

        for grp in await db.groups_db.active_groups():
            try:
                await ctx.bot.unban_chat_member(grp["chat_id"], target_id, only_if_banned=True)
            except Exception:
                pass

        try:
            await ctx.bot.send_message(
                target_id,
                f"Your appeal for ban <code>{ban_id}</code> has been approved. You have been unbanned.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        try:
            await q.edit_message_text(
                f"Appeal approved by {mention(admin.id, admin.first_name)}. User has been unbanned.",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

        try:
            await ctx.bot.send_message(
                lc,
                parse_logmsg.appeal_accepted(target_id, target_fname, admin.id, admin.first_name, ban_id),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception:
            pass

    elif action == "reject":
        try:
            await ctx.bot.send_message(
                target_id,
                f"Your appeal for ban <code>{ban_id}</code> has been rejected.",
                parse_mode="HTML",
            )
        except Exception:
            pass

        try:
            await q.edit_message_text(
                f"Appeal rejected by {mention(admin.id, admin.first_name)}.",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

        try:
            await ctx.bot.send_message(
                lc,
                parse_logmsg.appeal_rejected(target_id, target_fname, admin.id, admin.first_name, ban_id),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception:
            pass


## ---------------------------------------------------------------------------
## Handler factory
## ---------------------------------------------------------------------------

def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.Regex(r"^/start\s+appeal_\S+"),
                cmd_start_appeal_entry,
            ),
        ],
        states={
            WAITING_APPEAL: [
                CallbackQueryHandler(on_appeal_cancel, pattern=r"^cancel_appeal$"),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, on_appeal_message),
            ],
        },
        fallbacks=[
            MessageHandler(filters.COMMAND, lambda u, c: ConversationHandler.END),
        ],
        conversation_timeout=cfg.appeal_timeout,
        per_chat=False,
        per_user=True,
        per_message=False,
    )
