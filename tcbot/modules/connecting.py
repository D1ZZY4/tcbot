# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group affiliation – bot join/leave events and manual join command."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import CallbackQueryHandler, ChatMemberHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.workflows.connected_flow import on_bot_added, on_join_decision
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Connect"
__help_text__ = (
    "<code>/jointc</code> – request affiliation with TCF (group admin only).\n"
    "Aliases: <code>/requestjoin</code>, <code>/applytc</code>\n\n"
    "When the bot is added to a group, it automatically prompts the group owner to join TCF."
)


async def cmd_jointc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("Use this command in a group.")
        return

    member = await ctx.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator", "creator"):
        await update.effective_message.reply_text("Only group admins can request affiliation.")
        return

    if await db.groups_db.is_affiliated(chat.id):
        await update.effective_message.reply_text("Already affiliated.")
        return

    if await db.groups_db.get_pending(chat.id):
        await update.effective_message.reply_text("A join request for this group is already pending.")
        return

    ## Check bot permissions
    from tcbot.modules.helper.workflows.connected_flow import _REQUIRED_PERMS, _check_bot_perms
    try:
        bot_member = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
    except Exception:
        await update.effective_message.reply_text("Could not verify bot permissions.")
        return

    if not _check_bot_perms(bot_member):
        await update.effective_message.reply_text(
            "Please make the bot an admin with the necessary permissions "
            "(delete messages, ban users, invite users) and try again."
        )
        return

    ## Permissions OK – affiliate directly
    from tcbot.modules.helper.workflows.connected_flow import _complete_join
    await _complete_join(chat.id, chat.title or "", user.id, user.first_name, ctx.bot)
    await update.effective_message.reply_text("This community is now affiliated with TCF.")


## Spec aliases: /jointc, /requestjoin, /applytc
_JOINT_FILTER = (
    build_prefixed_filters("jointc")
    | build_prefixed_filters("requestjoin")
    | build_prefixed_filters("applytc")
)

__handlers__ = [
    ChatMemberHandler(on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER),
    MessageHandler(_JOINT_FILTER, cmd_jointc),
    CallbackQueryHandler(on_join_decision, pattern=r"^(tc_join|tc_cancel)$"),
]
