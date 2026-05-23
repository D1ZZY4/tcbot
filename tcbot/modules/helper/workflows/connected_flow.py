# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group connection flow – in-group join prompt, permission check, pending monitoring."""

from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.utils.dispatch import fan_out

log = logging.getLogger(__name__)

_REQUIRED_PERMS: tuple[str, ...] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)


class BuildConnection:
    """Configurable group-connection flow builder."""

    def __init__(
        self,
        community_name: str,
        *,
        required_perms: tuple[str, ...] = _REQUIRED_PERMS,
        join_label: str = "Connect",
        cancel_label: str = "Cancel",
        join_callback: str = "tc_join",
        cancel_callback: str = "tc_cancel",
    ) -> None:
        self.community_name = community_name
        self.required_perms = required_perms
        self.join_label = join_label
        self.cancel_label = cancel_label
        self.join_callback = join_callback
        self.cancel_callback = cancel_callback

    # ── Text factories ─────────────────────────────────────────────────────

    def join_prompt(self) -> str:
        """Initial prompt sent when the bot is first added to a group."""
        return f"Want to connect this group to {self.community_name}?"

    def connected_message(self) -> str:
        """Shown (or edited into the prompt) on a successful connection."""
        return (
            f"This community is now connected to {self.community_name}. "
            "Authorized staff can use federation commands here."
        )

    def declined_message(self) -> str:
        """Shown when the owner taps Cancel on the join prompt."""
        return "Connection declined. I'll leave the group now."

    def already_connected_message(self) -> str:
        """Shown when the group is already part of the federation."""
        return f"This group is already connected to {self.community_name}."

    def perms_required_message(self) -> str:
        """Shown when the bot lacks the required admin permissions."""
        return (
            "Please make the bot an admin with the required permissions "
            "(delete messages, ban users, invite users) and try again."
        )

    # ── Keyboard factory ───────────────────────────────────────────────────

    def join_keyboard(self) -> InlineKeyboardMarkup:
        """Connect / Cancel inline keyboard attached to the join prompt."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        self.join_label, callback_data=self.join_callback
                    ),
                    InlineKeyboardButton(
                        self.cancel_label, callback_data=self.cancel_callback
                    ),
                ]
            ]
        )

    # ── Permission check ───────────────────────────────────────────────────

    def check_perms(self, member) -> bool:
        """Return True when member holds every permission in required_perms."""
        return all(getattr(member, p, False) for p in self.required_perms)

    # ── Connection executor ────────────────────────────────────────────────

    async def complete_join(
        self,
        chat_id: int,
        chat_title: str,
        owner_id: int,
        owner_fname: str,
        bot,
    ) -> None:
        """Connect the group, apply all active federation bans, and notify LOG_CHANNEL."""
        # * Fetch chat info + active ban IDs + register group + clear pending - all in parallel
        chat_result, ban_uids, *_ = await asyncio.gather(
            bot.get_chat(chat_id),
            db.bans_db.active_ban_user_ids(),
            db.groups_db.add_group(chat_id, chat_title, owner_id),
            db.groups_db.remove_pending(chat_id),
            return_exceptions=True,
        )
        chat_username: str | None = (
            getattr(chat_result, "username", None)
            if not isinstance(chat_result, BaseException)
            else None
        )
        if isinstance(ban_uids, BaseException):
            ban_uids = []

        # * Apply all existing federation bans concurrently - semaphore-bounded
        results = await fan_out([bot.ban_chat_member(chat_id, uid) for uid in ban_uids])
        applied = sum(1 for r in results if not isinstance(r, BaseException))

        lc, lt = cfg.logs
        try:
            await bot.send_message(
                lc,
                parse_logmsg.group_connected_log(
                    chat_id, chat_title, owner_id, owner_fname, chat_username
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception as exc:
            log.error("Group connect log failed: %s", exc)

        log.info(
            "Group %d ('%s') connected. %d bans applied.", chat_id, chat_title, applied
        )

    # ── PTB event handlers ─────────────────────────────────────────────────

    async def on_bot_added(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Fired on every change to the bot's own member status in any chat."""
        cmc = update.my_chat_member
        if not cmc:
            return

        chat = cmc.chat
        if chat.type not in ("group", "supergroup"):
            return

        new_status = cmc.new_chat_member.status
        by_user = cmc.from_user
        lc, lt = cfg.logs

        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            # * is_connected, deactivate, and remove_pending all run in parallel
            was_connected, *_ = await asyncio.gather(
                db.groups_db.is_connected(chat.id),
                db.groups_db.deactivate_group(chat.id),
                db.groups_db.remove_pending(chat.id),
            )
            if was_connected:
                try:
                    await ctx.bot.send_message(
                        lc,
                        parse_logmsg.group_bot_removed_log(
                            chat.id, chat.title or "Unknown"
                        ),
                        parse_mode="HTML",
                        message_thread_id=lt,
                    )
                except Exception as exc:
                    log.error("Bot removed log failed for %d: %s", chat.id, exc)
            log.info("Bot removed from %d – group deactivated", chat.id)
            return

        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            pending = await db.groups_db.get_pending(chat.id)

            if pending and new_status == ChatMemberStatus.ADMINISTRATOR:
                if self.check_perms(cmc.new_chat_member):
                    owner_fname = await db.users_db.get_first_name(
                        pending["owner_id"], "Owner"
                    )
                    await self.complete_join(
                        chat.id,
                        chat.title or "",
                        pending["owner_id"],
                        owner_fname,
                        ctx.bot,
                    )
                    try:
                        await ctx.bot.edit_message_text(
                            self.connected_message(),
                            chat_id=chat.id,
                            message_id=pending["message_id"],
                            reply_markup=None,
                        )
                    except Exception as exc:
                        log.debug("Failed to edit pending connect prompt: %s", exc)
                return

            if await db.groups_db.is_connected(chat.id):
                return

            if pending:
                return

            try:
                prompt = await ctx.bot.send_message(
                    chat.id,
                    self.join_prompt(),
                    reply_markup=self.join_keyboard(),
                )
                await db.groups_db.add_pending(
                    chat.id,
                    chat.title or "",
                    by_user.id,
                    prompt.message_id,
                )
            except Exception as exc:
                log.error("Join prompt send failed for %d: %s", chat.id, exc)

    async def on_join_decision(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Callback handler for Connect / Cancel buttons on the join prompt."""
        q = update.callback_query
        chat = update.effective_chat
        user = update.effective_user
        lc, lt = cfg.logs

        try:
            member = await ctx.bot.get_chat_member(chat.id, user.id)
        except Exception as exc:
            log.debug("Join decision role check failed: %s", exc)
            await q.answer("Could not verify your role.", show_alert=True)
            return

        if member.status != ChatMemberStatus.OWNER:
            await q.answer("Only the group owner can decide.", show_alert=True)
            return

        action = q.data  # * sync read before any await

        if action == self.join_callback:
            try:
                _, bot_member = await asyncio.gather(
                    q.answer(),
                    ctx.bot.get_chat_member(chat.id, ctx.bot.id),
                )
            except Exception as exc:
                log.debug("Join decision permission check failed: %s", exc)
                await q.edit_message_text(
                    "Could not verify my own permissions. Please promote me as admin and try again.",
                    reply_markup=None,
                )
                return

            if not self.check_perms(bot_member):
                await db.groups_db.add_pending(
                    chat.id,
                    chat.title or "",
                    user.id,
                    q.message.message_id,
                )
                await q.edit_message_text(
                    self.perms_required_message(), reply_markup=None
                )
                return

            if await db.groups_db.is_connected(chat.id):
                await q.edit_message_text(
                    self.already_connected_message(), reply_markup=None
                )
                return

            await asyncio.gather(
                self.complete_join(
                    chat.id, chat.title or "", user.id, user.first_name, ctx.bot
                ),
                q.edit_message_text(self.connected_message(), reply_markup=None),
            )

        elif action == self.cancel_callback:
            await asyncio.gather(
                q.answer(),
                db.groups_db.remove_pending(chat.id),
                q.edit_message_text(self.declined_message(), reply_markup=None),
            )

            await asyncio.gather(
                ctx.bot.send_message(
                    lc,
                    parse_logmsg.group_connection_rejected_log(
                        chat.id,
                        chat.title or "Unknown",
                        user.id,
                        user.first_name,
                    ),
                    parse_mode="HTML",
                    message_thread_id=lt,
                ),
                ctx.bot.leave_chat(chat.id),
                return_exceptions=True,
            )


# ────────────────────── Module-level instance ───────────────────── #

connection = BuildConnection(cfg.community_name)
