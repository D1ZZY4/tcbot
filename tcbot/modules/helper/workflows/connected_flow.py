# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group affiliation flow – in-group join prompt, permission check, pending monitoring."""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot import cfg
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.keyboards import join_group_kb
from tcbot.utils.dispatch import fan_out

log = logging.getLogger(__name__)

_REQUIRED_PERMS = ("can_delete_messages", "can_restrict_members", "can_invite_users")


def _check_bot_perms(member) -> bool:
    return all(getattr(member, p, False) for p in _REQUIRED_PERMS)


async def _complete_join(chat_id: int, chat_title: str, owner_id: int, owner_fname: str, bot) -> None:
    """Affiliate the group, apply all active bans, and notify LOG_CHANNEL."""
    chat_username: str | None = None
    try:
        chat_info = await bot.get_chat(chat_id)
        chat_username = chat_info.username
    except Exception:
        pass

    await db.groups_db.add_group(chat_id, chat_title, owner_id)
    await db.groups_db.remove_pending(chat_id)

    ## Apply all existing federation bans concurrently — semaphore-bounded
    bans    = await db.bans_db.active_bans()
    results = await fan_out(
        [bot.ban_chat_member(chat_id, ban["banned_user_id"]) for ban in bans]
    )
    applied = sum(1 for r in results if not isinstance(r, BaseException))

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
    by_user    = cmc.from_user
    lc, lt     = cfg.logs

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

    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        pending = await db.groups_db.get_pending(chat.id)

        if pending and new_status == ChatMemberStatus.ADMINISTRATOR:
            if _check_bot_perms(cmc.new_chat_member):
                owner_fname = await db.users_db.get_first_name(pending["owner_id"], "Owner")
                await _complete_join(
                    chat.id, chat.title or "", pending["owner_id"], owner_fname, ctx.bot,
                )
                try:
                    await ctx.bot.edit_message_text(
                        f"This community is now affiliated with {cfg.community_name}. "
                        "Authorized staff can use federation commands here.",
                        chat_id=chat.id,
                        message_id=pending["message_id"],
                        reply_markup=None,
                    )
                except Exception:
                    pass
            return

        if await db.groups_db.is_affiliated(chat.id):
            return

        if pending:
            return

        try:
            prompt = await ctx.bot.send_message(
                chat.id,
                f"Want to affiliate this community with {cfg.community_name}?",
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
    q    = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    lc, lt = cfg.logs

    try:
        member = await ctx.bot.get_chat_member(chat.id, user.id)
    except Exception:
        await q.answer("Could not verify your role.", show_alert=True)
        return

    if member.status != ChatMemberStatus.OWNER:
        await q.answer("Only the group owner can decide.", show_alert=True)
        return

    action = q.data  ## sync read before any await

    if action == "tc_join":
        try:
            _, bot_member = await asyncio.gather(
                q.answer(),
                ctx.bot.get_chat_member(chat.id, ctx.bot.id),
            )
        except Exception:
            await q.edit_message_text(
                "Could not verify my own permissions. Please promote me as admin and try again.",
                reply_markup=None,
            )
            return

        if not _check_bot_perms(bot_member):
            await db.groups_db.add_pending(
                chat.id, chat.title or "", user.id, q.message.message_id,
            )
            await q.edit_message_text(
                "I need admin permissions first — delete messages, ban users, and invite users. "
                "Grant those and try again.",
                reply_markup=None,
            )
            return

        if await db.groups_db.is_affiliated(chat.id):
            await q.edit_message_text(f"This group is already affiliated with {cfg.community_name}.", reply_markup=None)
            return

        await asyncio.gather(
            _complete_join(chat.id, chat.title or "", user.id, user.first_name, ctx.bot),
            q.edit_message_text(
                f"This community is now affiliated with {cfg.community_name}. "
                "Authorized staff can use federation commands here.",
                reply_markup=None,
            ),
        )

    elif action == "tc_cancel":
        await asyncio.gather(
            q.answer(),
            db.groups_db.remove_pending(chat.id),
            q.edit_message_text("Affiliation declined. I'll leave the group now.", reply_markup=None),
        )

        await asyncio.gather(
            ctx.bot.send_message(
                lc,
                parse_logmsg.group_affiliation_rejected_log(
                    chat.id, chat.title or "Unknown", user.id, user.first_name,
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            ),
            ctx.bot.leave_chat(chat.id),
            return_exceptions=True,
        )
