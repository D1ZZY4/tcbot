# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group connection command and bot-added event handler for joining the federation."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
)

from tcbot import cfg, database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.workflows.connected_flow import connection
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)


## ── Module & Help ─────────────────────────────────────────────────────────

__module_name__ = "Connect"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcconnect</code> (alias: <code>/tccon</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Group admins and creators only (checked per-group).\n\n"

    "<b>Where to use it</b>\n"
    f"Inside the group you want to connect to {cfg.community_name}.\n\n"

    "<b>What it does</b>\n"
    f"Connects your group to the {cfg.community_name} federation. Once connected:\n"
    "- Federation bans are automatically enforced - any currently banned user in your group "
    "will be removed, and newly banned users will be kicked on ban.\n"
    "- Federation mutes are applied when issued.\n"
    "- Broadcast messages from TC Staff will be forwarded to your group.\n\n"
    "Before running the command, make the bot a group admin with these three permissions: "
    "<b>Delete Messages</b>, <b>Ban Users</b>, and <b>Invite Users via Link</b>.\n\n"
    "If a connect request is already pending for your group, a second request will be rejected - "
    "wait for TC Staff to process the existing one.\n\n"
    "When the bot is first added to a group, it automatically prompts the group owner to "
    "connect - so you can also just add the bot and follow that prompt.\n\n"

    "<b>Example</b>\n"
    "Make the bot a group admin, then run <code>/tcconnect</code> inside the group."
)


## ── /tcconnect command ─────────────────────────────────────────────────────

@decorators.ratelimiter(limit=3, period=60)
@decorators.log_execution
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

    ## Both DB reads are independent - run them in parallel
    is_connected, pending = await asyncio.gather(
        db.groups_db.is_connected(chat.id),
        db.groups_db.get_pending(chat.id),
    )
    if is_connected:
        await update.effective_message.reply_text(connection.already_connected_message())
        return

    if pending:
        await update.effective_message.reply_text(
            "A connect request for this group is already pending."
        )
        return

    try:
        bot_member = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
    except Exception:
        await update.effective_message.reply_text("Could not verify bot permissions.")
        return

    if not connection.check_perms(bot_member):
        await update.effective_message.reply_text(connection.perms_required_message())
        return

    ## complete_join returns None - reply can be sent in parallel
    await asyncio.gather(
        connection.complete_join(chat.id, chat.title or "", user.id, user.first_name, ctx.bot),
        update.effective_message.reply_text(connection.connected_message()),
    )


## ── Handlers ───────────────────────────────────────────────────────────────

_CONNECT_CMDS = (
    build_prefixed_filters("tcconnect")
    | build_prefixed_filters("tccon")
)

__handlers__ = [
    ChatMemberHandler(connection.on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER),
    MessageHandler(_CONNECT_CMDS, cmd_tcconnect),
    CallbackQueryHandler(
        connection.on_join_decision,
        pattern=rf"^({connection.join_callback}|{connection.cancel_callback})$",
    ),
]
