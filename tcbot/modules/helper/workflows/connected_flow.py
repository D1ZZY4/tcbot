# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group affiliation flow – in-group join prompt, permission check, pending monitoring."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import esc

log = logging.getLogger(__name__)

## Required bot permissions for federation enforcement
_REQUIRED_PERMS = ("can_delete_messages", "can_restrict_members", "can_invite_users")


def _check_bot_perms(member) -> bool:
    return all(getattr(member, p, False) for p in _REQUIRED_PERMS)


async def _complete_join(chat_id: int, chat_title: str, owner_id: int, owner_fname: str, bot) -> None:
    """Affiliate the group, apply all active bans, and notify LOG_CHANNEL."""
    ## Try to get chat username
    chat_username: str | None = None
    try:
        chat_info = await bot.get_chat(chat_id)
        chat_username = chat_info.username
    except Exception:
        pass

    await db.groups_db.add_group(chat_id, chat_title, owner_id)
    await db.groups_db.remove_pending(chat_id)

    ## Apply all existing federation bans
    bans = await db.bans_db.active_bans()
    applied = 0
    for ban in bans:
        try:
            await bot.ban_chat_member(chat_id, ban["banned_user_id"])
            applied += 1
        except Exception:
            pass

    ## Log to LOG_CHANNEL
    lc, lt = cfg.logs
    log_text = parse_logmsg.group_connected_log(
        chat_id, chat_title, owner_id, owner_fname, chat_username,
    )
    try:
        await bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Group connect log failed: %s", exc)

    log.info("Group %d ('%s') affiliated. %d bans applied.", chat_id, chat_title, applied)


## ---------------------------------------------------------------------------
## my_chat_member handler
## ---------------------------------------------------------------------------

async def on_bot_added(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
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

    ## Bot was removed or kicked
    if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        was_affiliated = await db.groups_db.is_affiliated(chat.id)
        await db.groups_db.deactivate_group(chat.id)
        await db.groups_db.remove_pending(chat.id)
        if was_affiliated:
            try:
                await ctx.bot.send_message(
                    lc,
                    parse_logmsg.group_bot_removed_log(chat.id, chat.title or "Unknown"),
                    parse_mode="HTML",
                    message_thread_id=lt,
                )
            except Exception:
                pass
        log.info("Bot removed from %d – group deactivated", chat.id)
        return

    ## Bot was added or promoted
    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        ## Check if there's a pending join for this chat
        pending = await db.groups_db.get_pending(chat.id)

        if pending and new_status == ChatMemberStatus.ADMINISTRATOR:
            ## Was waiting for admin rights – check perms and complete if sufficient
            if _check_bot_perms(cmc.new_chat_member):
                owner_fname = await db.users_db.get_first_name(pending["owner_id"], "Owner")
                await _complete_join(
                    chat.id, chat.title or "", pending["owner_id"], owner_fname, ctx.bot,
                )
                ## Edit stored prompt message to success
                try:
                    await ctx.bot.edit_message_text(
                        "This community is now affiliated with TCF. "
                        "Federation commands can now be used here by authorized Transsion Core admins.",
                        chat_id=chat.id,
                        message_id=pending["message_id"],
                        reply_markup=None,
                    )
                except Exception:
                    pass
            return

        ## Already affiliated – nothing to do
        if await db.groups_db.is_affiliated(chat.id):
            return

        if pending:
            return  ## Already have a pending entry; waiting for permissions

        ## Fresh add – send join prompt in the group
        from tcbot.modules.helper.keyboards import join_group_kb
        try:
            prompt = await ctx.bot.send_message(
                chat.id,
                "Do you want this community to join the Transsion Core Federation?",
                reply_markup=join_group_kb(),
            )
            await db.groups_db.add_pending(
                chat.id, chat.title or "", by_user.id, prompt.message_id,
            )
        except Exception as exc:
            log.error("Join prompt send failed for %d: %s", chat.id, exc)


## ---------------------------------------------------------------------------
## Inline button callbacks (tc_join / tc_cancel)
## ---------------------------------------------------------------------------

async def on_join_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    lc, lt = cfg.logs

    ## Only the group creator (owner) may decide
    try:
        member = await ctx.bot.get_chat_member(chat.id, user.id)
    except Exception:
        await q.answer("Could not verify your role.", show_alert=True)
        return

    if member.status != ChatMemberStatus.OWNER:
        await q.answer("Only the group owner can decide.", show_alert=True)
        return

    await q.answer()
    action = q.data  ## "tc_join" or "tc_cancel"

    if action == "tc_join":
        ## Check bot permissions
        try:
            bot_member = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
        except Exception:
            await q.edit_message_text(
                "Could not verify my own permissions. Please promote me as admin and try again.",
                reply_markup=None,
            )
            return

        if not _check_bot_perms(bot_member):
            ## Store pending and ask user to promote bot
            await db.groups_db.add_pending(
                chat.id, chat.title or "", user.id, q.message.message_id,
            )
            await q.edit_message_text(
                "Please make the bot an admin with the necessary permissions "
                "(delete messages, ban users, invite users) and try again.",
                reply_markup=None,
            )
            return

        ## Permissions OK – affiliate
        if await db.groups_db.is_affiliated(chat.id):
            await q.edit_message_text("Already affiliated.", reply_markup=None)
            return

        await _complete_join(chat.id, chat.title or "", user.id, user.first_name, ctx.bot)

        bans = await db.bans_db.active_bans()
        await q.edit_message_text(
            "This community is now affiliated with TCF. "
            "Federation commands can now be used here by authorized Transsion Core admins.",
            reply_markup=None,
        )

    elif action == "tc_cancel":
        pending = await db.groups_db.get_pending(chat.id)
        await db.groups_db.remove_pending(chat.id)
        await q.edit_message_text("Affiliation cancelled. Leaving the group.", reply_markup=None)

        ## Log rejection
        try:
            await ctx.bot.send_message(
                lc,
                parse_logmsg.group_affiliation_rejected_log(
                    chat.id, chat.title or "Unknown", user.id, user.first_name,
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception:
            pass

        try:
            await ctx.bot.leave_chat(chat.id)
        except Exception:
            pass
