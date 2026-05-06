# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Appeal conversation – entry via /start appeal<ban_id> deep link, DM only
from __future__ import annotations

import asyncio
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
from tcbot import cfg
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.dispatch import fan_out
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, ANY_CMD_FILTER

log = logging.getLogger(__name__)

WAITING_APPEAL = 0


async def _update_or_send_appeal_log(
    bot,
    lc: int,
    lt: int | None,
    msg_id: int | None,
    text: str,
) -> None:
    """Edit the existing appeal log message in the log channel, or send a new one as fallback."""
    if msg_id:
        try:
            await bot.edit_message_text(text, chat_id=lc, message_id=msg_id, parse_mode="HTML")
            return
        except Exception as exc:
            log.warning("Could not edit appeal submitted log: %s", exc)
    try:
        await bot.send_message(lc, text, parse_mode="HTML", message_thread_id=lt)
    except Exception:
        pass


_ID_RE = re.compile(r"^/start\s+appeal_([a-z0-9]{10})$")

_INSTRUCTION_TEXT = (
    f"{cfg.community_name} Ban Appeal\n\n"
    "To submit your appeal, reply with a message starting with <code>#appeal</code>, containing:\n"
    "- <b>Log link:</b> (the link to your ban log from the log channel)\n"
    "- <b>Clarification:</b> (your honest explanation of what happened)\n"
    "- <b>Agreement:</b> (your commitment not to repeat the violation)\n\n"
    "<b>Example:</b>\n"
    "<pre>#appeal\n"
    "Log link: https://t.me/TranssionCoreFederationLogs/1\n"
    "Clarification: I spammed unintentionally due to an auto-clicker.\n"
    "Agreement: I will not use any automation tools in the group again.</pre>\n\n"
    "Log Channel: @TranssionCoreFederationLogs"
)


async def start_appeal(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ban_id: str) -> int:
    msg = update.effective_message
    uid = update.effective_user.id

    if update.effective_chat.type != "private":
        await msg.reply_text("Please open this link in my private messages.")
        return ConversationHandler.END

    ban = await db.bans_db.get_ban(ban_id)
    if not ban or not ban.get("is_active"):
        await msg.reply_text("This appeal link is invalid or has expired.")
        return ConversationHandler.END

    if ban["banned_user_id"] != uid:
        await msg.reply_text("This appeal link doesn't belong to your account.")
        return ConversationHandler.END

    if ban.get("review_message_id"):
        await msg.reply_text("You already have a pending appeal under review.")
        return ConversationHandler.END

    ctx.user_data["appeal_ban_id"]     = ban_id
    ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)

    instr = await msg.reply_text(
        _INSTRUCTION_TEXT,
        parse_mode="HTML",
        reply_markup=keyboards.appeal_cancel_kb(),
    )
    ctx.user_data["appeal_instruction_msg_id"] = instr.message_id

    return WAITING_APPEAL


async def cmd_start_appeal_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    m    = _ID_RE.match(text)
    if not m:
        return ConversationHandler.END
    return await start_appeal(update, ctx, m.group(1))


async def on_appeal_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    for key in ("appeal_ban_id", "appeal_log_msg_id", "appeal_instruction_msg_id"):
        ctx.user_data.pop(key, None)
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Appeal cancelled. Nothing was submitted."),
    )
    return ConversationHandler.END


async def on_appeal_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg  = update.effective_message
    text = (msg.text or "").strip()

    if not text.startswith("#appeal"):
        return WAITING_APPEAL

    ban_id     = ctx.user_data.get("appeal_ban_id")
    log_msg_id = ctx.user_data.get("appeal_log_msg_id", 0)

    if not ban_id:
        await msg.reply_text("Session expired — please start the appeal again.")
        return ConversationHandler.END

    if log_msg_id and not re.search(rf"\b{log_msg_id}\b", text):
        await msg.reply_text("Invalid log link. Please check and try again.")
        return WAITING_APPEAL

    uid  = update.effective_user.id
    user = update.effective_user

    appeal_chat, appeal_thread = cfg.appeals
    appeal_msg_id: int | None = None
    try:
        fwd           = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
        appeal_msg_id = fwd.message_id
    except Exception as exc:
        log.error("Appeal forward failed: %s", exc)

    appeal_link  = message_link(appeal_chat, appeal_msg_id, appeal_thread) if appeal_msg_id else ""
    review_text  = parse_logmsg.appeal_received_log(uid, user.first_name, ban_id, appeal_link)
    lc, lt       = cfg.logs

    ## Send review post + log message in parallel
    rv, sent_log = await asyncio.gather(
        ctx.bot.send_message(
            cfg.main_group,
            review_text,
            parse_mode="HTML",
            message_thread_id=cfg.appeal_discussion_topic or None,
            reply_markup=keyboards.appeal_review_kb(ban_id),
        ),
        ctx.bot.send_message(
            lc,
            parse_logmsg.appeal_submitted_log(uid, user.first_name, ban_id, appeal_link),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        return_exceptions=True,
    )

    review_msg_id: int | None = rv.message_id if not isinstance(rv, BaseException) else None
    if isinstance(rv, BaseException):
        log.error("Appeal review post failed: %s", rv)

    appeal_log_sent_id: int | None = sent_log.message_id if not isinstance(sent_log, BaseException) else None
    if isinstance(sent_log, BaseException):
        log.error("Appeal log failed: %s", sent_log)

    ## Store review + log msg IDs in DB in parallel
    db_tasks = []
    if review_msg_id:
        db_tasks.append(db.bans_db.set_review(ban_id, review_msg_id))
    if appeal_log_sent_id and ban_id:
        db_tasks.append(db.bans_db.set_appeal_log_msg(ban_id, appeal_log_sent_id, appeal_link=appeal_link))
    if db_tasks:
        await asyncio.gather(*db_tasks, return_exceptions=True)

    ## Edit instruction message + cache user in parallel
    instr_mid = ctx.user_data.get("appeal_instruction_msg_id")
    edit_coro = (
        ctx.bot.edit_message_text(
            "Your appeal has been submitted. The team will review it shortly — we'll get back to you.",
            chat_id=update.effective_chat.id,
            message_id=instr_mid,
        )
        if instr_mid else None
    )
    upsert_coro = db.users_db.upsert_user(uid, user.username, user.first_name, user.last_name)

    if edit_coro:
        await asyncio.gather(edit_coro, upsert_coro, return_exceptions=True)
    else:
        await upsert_coro

    return ConversationHandler.END


async def on_appeal_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q     = update.callback_query
    admin = update.effective_user

    if not await db.admins_db.is_staff(admin.id):
        await q.answer("You are not authorized.", show_alert=True)
        return

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

    _, ban = await asyncio.gather(q.answer(), db.bans_db.get_ban(ban_id))
    if not ban:
        await q.edit_message_text("Ban record not found.", reply_markup=None)
        return

    if not ban.get("is_active"):
        await q.edit_message_text("Appeal already resolved (ban is no longer active).", reply_markup=None)
        return

    review_ts = ban.get("review_timestamp")
    if review_ts:
        elapsed = datetime.now(timezone.utc) - review_ts.replace(tzinfo=timezone.utc)
        if elapsed < timedelta(hours=12) and admin.id != ban.get("admin_user_id"):
            await q.answer(
                "Only the admin who issued this ban can review it within the first 12 hours.",
                show_alert=True,
            )
            return

    target_id = ban["banned_user_id"]
    lc, lt    = cfg.logs

    if action == "approve":
        ## Deactivate ban + fetch active groups + fetch target name — all in parallel
        _, groups, target_fname = await asyncio.gather(
            db.bans_db.deactivate_ban(ban_id),
            db.groups_db.active_groups(),
            db.users_db.get_first_name(target_id, str(target_id)),
        )

        ## Unban from all groups — semaphore-bounded for rate safety
        await fan_out(
            [ctx.bot.unban_chat_member(grp["chat_id"], target_id, only_if_banned=True)
             for grp in groups]
        )

        ## Notify user + edit review message in parallel
        await asyncio.gather(
            ctx.bot.send_message(
                target_id,
                f"Your appeal for ban <code>{ban_id}</code> has been approved — "
                f"you're now unbanned from {cfg.community_name}. Welcome back.",
                parse_mode="HTML",
            ),
            q.edit_message_text(
                f"Appeal approved by {mention(admin.id, admin.first_name)}. User unbanned.",
                parse_mode="HTML",
                reply_markup=None,
            ),
            return_exceptions=True,
        )

        ## Edit the submitted appeal log message in LOG_CHANNEL
        appeal_log_msg_id   = ban.get("appeal_log_msg_id")
        appeal_submitted_at = ban.get("appeal_submitted_at")
        appeal_link         = ban.get("appeal_link", "")
        await _update_or_send_appeal_log(
            ctx.bot, lc, lt, appeal_log_msg_id,
            parse_logmsg.appeal_approved_edit(
                target_id, target_fname,
                admin.id, admin.first_name,
                ban_id, appeal_link, appeal_submitted_at,
            ),
        )

        ## Send separate unban log
        try:
            await ctx.bot.send_message(
                lc,
                parse_logmsg.appeal_unban_log(
                    target_id, target_fname, admin.id, admin.first_name, ban_id,
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception as exc:
            log.error("Appeal unban log failed: %s", exc)

    elif action == "reject":
        ## Fetch target name + notify user + edit review message — all in parallel
        target_fname_result, *_ = await asyncio.gather(
            db.users_db.get_first_name(target_id, str(target_id)),
            ctx.bot.send_message(
                target_id,
                f"Your appeal for ban <code>{ban_id}</code> has been reviewed and not approved. "
                "The ban remains in place.",
                parse_mode="HTML",
            ),
            q.edit_message_text(
                f"Appeal rejected by {mention(admin.id, admin.first_name)}.",
                parse_mode="HTML",
                reply_markup=None,
            ),
            return_exceptions=True,
        )
        target_fname = (
            target_fname_result
            if not isinstance(target_fname_result, BaseException)
            else str(target_id)
        )

        ## Edit the submitted appeal log message in LOG_CHANNEL
        appeal_log_msg_id   = ban.get("appeal_log_msg_id")
        appeal_submitted_at = ban.get("appeal_submitted_at")
        appeal_link         = ban.get("appeal_link", "")
        await _update_or_send_appeal_log(
            ctx.bot, lc, lt, appeal_log_msg_id,
            parse_logmsg.appeal_rejected_edit(
                target_id, target_fname,
                admin.id, admin.first_name,
                ban_id, appeal_link, appeal_submitted_at,
            ),
        )


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.Regex(r"^/start\s+appeal_[a-z0-9]{10}$"),
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
            MessageHandler(ALL_PREFIXES_CMD_FILTER, lambda u, c: ConversationHandler.END),
        ],
        conversation_timeout=cfg.appeal_timeout,
        per_chat=False,
        per_user=True,
        per_message=False,
    )
