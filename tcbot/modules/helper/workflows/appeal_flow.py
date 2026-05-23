# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Appeal conversation – entry via /start appeal<ban_id> deep link, DM only
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.dispatch import fan_out
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.timedate_format import to_utc, utc_now

log = logging.getLogger(__name__)

WAITING_APPEAL = 0
_LOCK_WINDOW = timedelta(hours=12)

_ID_RE = re.compile(r"^/start\s+appeal_([a-z0-9]{10})$")


class BuildAppeal:
    """Configurable appeal ConversationHandler builder.

    All user-visible strings and callback identifiers are injected at
    construction time — the class contains no community-specific hardcoded
    values.  Each constructor parameter changes a distinct aspect of the
    appeal flow:

    - ``community_name`` — shown in the instruction header and approval DMs
    - ``log_channel``    — @handle shown at the bottom of the instruction text
    - ``cancel_label``   — label on the Cancel button during the waiting state
    - ``cancel_callback`` — ``callback_data`` value for that button (also used
                            as the ``CallbackQueryHandler`` pattern inside
                            ``build_handler()``)
    """

    def __init__(
        self,
        community_name: str,
        log_channel: str,
        *,
        cancel_label: str = "Cancel",
        cancel_callback: str = "cancel_appeal",
    ) -> None:
        self.community_name = community_name
        self.log_channel = log_channel
        self.cancel_label = cancel_label
        self.cancel_callback = cancel_callback

    # ── Keyboard and text factories ────────────────────────────────────────

    def instruction_text(self) -> str:
        """Multi-line HTML instruction prompt sent when the user opens an appeal."""
        log_handle = self.log_channel.lstrip("@")
        return (
            f"{self.community_name} Ban Appeal\n\n"
            "To submit your appeal, reply with a message starting with <code>#appeal</code>, containing:\n"
            "- <b>Log link:</b> (the link to your ban log from the log channel)\n"
            "- <b>Clarification:</b> (your honest explanation of what happened)\n"
            "- <b>Agreement:</b> (your commitment not to repeat the violation)\n\n"
            "<b>Example:</b>\n"
            "<pre>#appeal\n"
            f"Log link: https://t.me/{log_handle}/1\n"
            "Clarification: I spammed unintentionally due to an auto-clicker.\n"
            "Agreement: I will not use any automation tools in the group again.</pre>\n\n"
            f"Log Channel: {self.log_channel}"
        )

    def cancel_keyboard(self) -> InlineKeyboardMarkup:
        """Single-button keyboard attached to the instruction prompt."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        self.cancel_label, callback_data=self.cancel_callback
                    )
                ]
            ]
        )

    def review_keyboard(self, ban_id: str) -> InlineKeyboardMarkup:
        """Approve / Reject keyboard attached to the staff review card."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Approve", callback_data=f"appeal_approve_{ban_id}"
                    ),
                    InlineKeyboardButton(
                        "Reject", callback_data=f"appeal_reject_{ban_id}"
                    ),
                ]
            ]
        )

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    async def _update_or_send_log(
        bot,
        lc: int,
        lt: int | None,
        msg_id: int | None,
        text: str,
    ) -> None:
        """Edit the existing appeal log message, or post a new one as fallback."""
        if msg_id:
            try:
                await bot.edit_message_text(
                    text, chat_id=lc, message_id=msg_id, parse_mode="HTML"
                )
                return
            except Exception as exc:
                log.warning("Could not edit appeal submitted log: %s", exc)
        try:
            await bot.send_message(lc, text, parse_mode="HTML", message_thread_id=lt)
        except Exception as exc:
            log.debug("Could not send appeal submitted log: %s", exc)

    # ── ConversationHandler step methods ──────────────────────────────────

    async def _start(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, ban_id: str
    ) -> int:
        """Validate the deep-link and open the WAITING_APPEAL state."""
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

        ctx.user_data["appeal_ban_id"] = ban_id
        ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)

        instr = await msg.reply_text(
            self.instruction_text(),
            parse_mode="HTML",
            reply_markup=self.cancel_keyboard(),
        )
        ctx.user_data["appeal_instruction_msg_id"] = instr.message_id

        return WAITING_APPEAL

    async def _on_entry(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry-point handler — parses the /start appeal_<id> deep link."""
        text = (update.effective_message.text or "").strip()
        m = _ID_RE.match(text)
        if not m:
            return ConversationHandler.END
        return await self._start(update, ctx, m.group(1))

    async def _on_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel button handler — clears state and ends the conversation."""
        q = update.callback_query
        for key in ("appeal_ban_id", "appeal_log_msg_id", "appeal_instruction_msg_id"):
            ctx.user_data.pop(key, None)
        await asyncio.gather(
            q.answer(),
            q.edit_message_text("Appeal cancelled. Nothing was submitted."),
        )
        return ConversationHandler.END

    async def _end(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Fallback handler — fires on any unrecognised command during the flow."""
        await update.effective_message.reply_text("Appeal session ended.")
        return ConversationHandler.END

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Text message handler — validates and submits a #appeal message."""
        msg = update.effective_message
        text = (msg.text or "").strip()

        if not text.startswith("#appeal"):
            return WAITING_APPEAL

        ban_id = ctx.user_data.get("appeal_ban_id")
        log_msg_id = ctx.user_data.get("appeal_log_msg_id", 0)

        if not ban_id:
            await msg.reply_text("Session expired - please start the appeal again.")
            return ConversationHandler.END

        if log_msg_id and not re.search(rf"\b{log_msg_id}\b", text):
            await msg.reply_text("Invalid log link. Please check and try again.")
            return WAITING_APPEAL

        uid = update.effective_user.id
        user = update.effective_user

        appeal_chat, appeal_thread = cfg.appeals
        appeal_msg_id: int | None = None
        try:
            fwd = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
            appeal_msg_id = fwd.message_id
        except Exception as exc:
            log.error("Appeal forward failed: %s", exc)

        appeal_link = (
            message_link(appeal_chat, appeal_msg_id, appeal_thread)
            if appeal_msg_id
            else ""
        )
        review_text = parse_logmsg.appeal_received_log(
            uid, user.first_name, ban_id, appeal_link
        )
        lc, lt = cfg.logs

        # * Send review post + log message in parallel
        rv, sent_log = await asyncio.gather(
            ctx.bot.send_message(
                cfg.main_group,
                review_text,
                parse_mode="HTML",
                message_thread_id=cfg.appeal_discussion_topic or None,
                reply_markup=self.review_keyboard(ban_id),
            ),
            ctx.bot.send_message(
                lc,
                parse_logmsg.appeal_submitted_log(
                    uid, user.first_name, ban_id, appeal_link
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            ),
            return_exceptions=True,
        )

        review_msg_id: int | None = (
            rv.message_id if not isinstance(rv, BaseException) else None
        )
        if isinstance(rv, BaseException):
            log.error("Appeal review post failed: %s", rv)

        appeal_log_sent_id: int | None = (
            sent_log.message_id if not isinstance(sent_log, BaseException) else None
        )
        if isinstance(sent_log, BaseException):
            log.error("Appeal log failed: %s", sent_log)

        # * Store review + log msg IDs in DB in parallel
        db_tasks = []
        if review_msg_id:
            db_tasks.append(db.bans_db.set_review(ban_id, review_msg_id))
        if appeal_log_sent_id and ban_id:
            db_tasks.append(
                db.bans_db.set_appeal_log_msg(
                    ban_id, appeal_log_sent_id, appeal_link=appeal_link
                )
            )
        if db_tasks:
            await asyncio.gather(*db_tasks, return_exceptions=True)

        # * Edit instruction message + cache user in parallel
        instr_mid = ctx.user_data.get("appeal_instruction_msg_id")
        edit_coro = (
            ctx.bot.edit_message_text(
                "Your appeal has been submitted. The team will review it shortly - we'll get back to you.",
                chat_id=update.effective_chat.id,
                message_id=instr_mid,
            )
            if instr_mid
            else None
        )
        upsert_coro = db.users_db.upsert_user(
            uid, user.username, user.first_name, user.last_name
        )

        if edit_coro:
            await asyncio.gather(edit_coro, upsert_coro, return_exceptions=True)
        else:
            await upsert_coro

        return ConversationHandler.END

    # ── Public callback handler (registered outside the ConversationHandler) ─

    async def on_decision(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Approve / Reject callback for the staff review card in the main group."""
        q = update.callback_query
        admin = update.effective_user

        if not await db.admins_db.is_staff(admin.id):
            await q.answer("You are not authorized.", show_alert=True)
            return

        data = q.data
        if data.startswith("appeal_approve_"):
            action = "approve"
            ban_id = data[len("appeal_approve_") :]
        elif data.startswith("appeal_reject_"):
            action = "reject"
            ban_id = data[len("appeal_reject_") :]
        else:
            await q.answer()
            return

        _, ban = await asyncio.gather(q.answer(), db.bans_db.get_ban(ban_id))
        if not ban:
            await q.edit_message_text("Ban record not found.", reply_markup=None)
            return

        if not ban.get("is_active"):
            await q.edit_message_text(
                "Appeal already resolved (ban is no longer active).", reply_markup=None
            )
            return

        review_ts = ban.get("review_timestamp")
        if review_ts:
            if reviewer_locked_out(review_ts, ban.get("admin_user_id"), admin.id):
                await q.answer(
                    "Only the admin who issued this ban can review it within the first 12 hours.",
                    show_alert=True,
                )
                return

        target_id = ban["banned_user_id"]
        lc, lt = cfg.logs

        if action == "approve":
            # * Deactivate ban + fetch active groups + fetch target name - all in parallel
            _, groups, target_fname = await asyncio.gather(
                db.bans_db.deactivate_ban(ban_id),
                db.groups_db.active_groups(),
                db.users_db.get_first_name(target_id, str(target_id)),
            )

            # * Unban from all groups - semaphore-bounded for rate safety
            await fan_out(
                [
                    ctx.bot.unban_chat_member(
                        grp["chat_id"], target_id, only_if_banned=True
                    )
                    for grp in groups
                ]
            )

            # * Notify user + edit review message in parallel
            await asyncio.gather(
                ctx.bot.send_message(
                    target_id,
                    f"Your appeal for ban <code>{ban_id}</code> has been approved - "
                    f"you're now unbanned from {self.community_name}. Welcome back.",
                    parse_mode="HTML",
                ),
                q.edit_message_text(
                    f"Appeal approved by {mention(admin.id, admin.first_name)}. User unbanned.",
                    parse_mode="HTML",
                    reply_markup=None,
                ),
                return_exceptions=True,
            )

            # * Edit the submitted appeal log message in LOG_CHANNEL
            await self._update_or_send_log(
                ctx.bot,
                lc,
                lt,
                ban.get("appeal_log_msg_id"),
                parse_logmsg.appeal_approved_edit(
                    target_id,
                    target_fname,
                    admin.id,
                    admin.first_name,
                    ban_id,
                    ban.get("appeal_link", ""),
                    ban.get("appeal_submitted_at"),
                ),
            )

            # * Send separate unban log
            try:
                await ctx.bot.send_message(
                    lc,
                    parse_logmsg.appeal_unban_log(
                        target_id,
                        target_fname,
                        admin.id,
                        admin.first_name,
                        ban_id,
                    ),
                    parse_mode="HTML",
                    message_thread_id=lt,
                )
            except Exception as exc:
                log.error("Appeal unban log failed: %s", exc)

        elif action == "reject":
            # * Fetch target name + notify user + edit review message - all in parallel
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

            # * Edit the submitted appeal log message in LOG_CHANNEL
            await self._update_or_send_log(
                ctx.bot,
                lc,
                lt,
                ban.get("appeal_log_msg_id"),
                parse_logmsg.appeal_rejected_edit(
                    target_id,
                    target_fname,
                    admin.id,
                    admin.first_name,
                    ban_id,
                    ban.get("appeal_link", ""),
                    ban.get("appeal_submitted_at"),
                ),
            )

    # ── ConversationHandler factory ────────────────────────────────────────

    def build_handler(self, entry_filter) -> ConversationHandler:
        """Assemble and return the appeal ConversationHandler."""
        return ConversationHandler(
            entry_points=[MessageHandler(entry_filter, self._on_entry)],
            states={
                WAITING_APPEAL: [
                    CallbackQueryHandler(
                        self._on_cancel,
                        pattern=rf"^{re.escape(self.cancel_callback)}$",
                    ),
                    MessageHandler(
                        filters.ChatType.PRIVATE & filters.TEXT, self._on_message
                    ),
                ],
            },
            fallbacks=[
                MessageHandler(ALL_PREFIXES_CMD_FILTER, self._end),
            ],
            conversation_timeout=cfg.appeal_timeout,
            per_chat=True,
            per_user=True,
            per_message=False,
        )


# ── Module-level instance ─────────────────────────────────────────────────

appeal = BuildAppeal(cfg.community_name, cfg.appeal_log_handle)


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """
    Check whether reviewer_id is blocked from reviewing within the lock window.

    Returns False when metadata is absent or reviewer is the original banning
    admin — they may always review their own bans. Returns True only if
    elapsed < _LOCK_WINDOW and reviewer is a different admin.
    """
    if review_timestamp is None or ban_admin_id is None:
        return False
    if reviewer_id == ban_admin_id:
        return False
    elapsed = utc_now() - to_utc(review_timestamp)
    return elapsed < _LOCK_WINDOW
