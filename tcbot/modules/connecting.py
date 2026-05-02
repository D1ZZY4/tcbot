# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group connect – bot join/leave events and manual connect command."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
)

from tcbot import cfg, database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.workflows.connected_flow import on_bot_added, on_join_decision
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Connect"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcconnect</code> — alias: <code>/tccon</code>\n\n"

    "<b>Who can use it</b>\n"
    "Group admins and creators only (checked per-group).\n\n"

    "<b>Where to use it</b>\n"
    f"Inside the group you want to connect to {cfg.community_name}.\n\n"

    "<b>What it does</b>\n"
    f"Connects your group to {cfg.community_name}. Once connected, the bot will "
    "automatically enforce federation bans in your group — banned users won't be able to stay.\n\n"
    "Before connecting, make sure the bot is an admin in the group with these permissions: "
    "<b>delete messages</b>, <b>ban users</b>, and <b>invite users</b>.\n\n"
    "When the bot is added to a group for the first time, it will automatically prompt "
    "the group owner to connect — so you can also just add the bot and follow the prompt.\n\n"

    "<b>Example</b>\n"
    "Add the bot as admin, then run <code>/tcconnect</code> inside the group."
)


async def cmd_tcconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("Use this command in a group.")
        return

    member = await ctx.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator", "creator"):
        await update.effective_message.reply_text(
            "Only group admins can request to connect."
        )
        return

    if await db.groups_db.is_affiliated(chat.id):
        await update.effective_message.reply_text(f"This group is already connected to {cfg.community_name}.")
        return

    if await db.groups_db.get_pending(chat.id):
        await update.effective_message.reply_text(
            "A connect request for this group is already pending."
        )
        return

    from tcbot.modules.helper.workflows.connected_flow import (
        _REQUIRED_PERMS,
        _check_bot_perms,
    )

    try:
        bot_member = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
    except Exception:
        await update.effective_message.reply_text("Could not verify bot permissions.")
        return

    if not _check_bot_perms(bot_member):
        await update.effective_message.reply_text(
            "Please make the bot an admin with the required permissions "
            "(delete messages, ban users, invite users) and try again."
        )
        return

    from tcbot.modules.helper.workflows.connected_flow import _complete_join
    await _complete_join(chat.id, chat.title or "", user.id, user.first_name, ctx.bot)
    await update.effective_message.reply_text(
        f"This group is now connected to {cfg.community_name}."
    )


_CONNECT_FILTER = (
    build_prefixed_filters("tcconnect")
    | build_prefixed_filters("tccon")
)

__handlers__ = [
    ChatMemberHandler(on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER),
    MessageHandler(_CONNECT_FILTER, cmd_tcconnect),
    CallbackQueryHandler(on_join_decision, pattern=r"^(tc_join|tc_cancel)$"),
]
