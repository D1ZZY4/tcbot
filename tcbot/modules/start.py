# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start command and main interactive menu callbacks."""
from __future__ import annotations

import asyncio
import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import cfg, database as db
from tcbot.modules.about import __about_msg__
from tcbot.modules.groups import _render
from tcbot.modules.helper import keyboards
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = None

_MENU_TEXT = (
    "<b>Hey! I'm {bot_name}. 👋</b>\n"
    "I manage {community} groups, federation bans, and appeals. "
    "Use the buttons below to explore."
)

_GROUP_START_TEXT = (
    "<b>Hey! I'm {bot_name}. 👋</b>\n"
    "I manage {community} groups, federation bans, and appeals.\n\n"
    "Use /help for all available commands, or open me in PM for the full menu."
)


## ---------------------------------------------------------------------------
## /start command
## ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg      = update.effective_message
    chat     = update.effective_chat
    text     = (msg.text or "").strip()
    parts    = text.split(None, 1)
    arg      = parts[1].strip() if len(parts) > 1 else ""
    bot_name = ctx.bot.first_name or "TC Bot"

    ## Group / supergroup context — send a minimal message with PM link
    if chat.type in ("group", "supergroup"):
        bot_username = ctx.bot.username or ""
        await msg.reply_text(
            _GROUP_START_TEXT.format(bot_name=bot_name, community=cfg.community_name),
            parse_mode="HTML",
            reply_markup=keyboards.group_start_kb(bot_username),
        )
        return

    ## PM context below
    if arg == "about":
        await msg.reply_text(
            __about_msg__, parse_mode="HTML",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return

    ## appeal<ban_id> deep links are handled by the ConversationHandler in appeals.py
    await msg.reply_text(
        _MENU_TEXT.format(bot_name=bot_name, community=cfg.community_name),
        parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


## ---------------------------------------------------------------------------
## Menu callbacks
## ---------------------------------------------------------------------------

async def on_menu_back_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    bot_name = ctx.bot.first_name or "TC Bot"
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _MENU_TEXT.format(bot_name=bot_name, community=cfg.community_name),
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_kb(),
        ),
    )


def _groups_menu_kb(detailed: bool) -> InlineKeyboardMarkup:
    toggle = InlineKeyboardButton(
        "Simple" if detailed else "Details",
        callback_data="menu_groups_simple" if detailed else "menu_groups_details",
    )
    back = InlineKeyboardButton("« Back", callback_data="menu_back_start")
    return InlineKeyboardMarkup([[toggle], [back]])


async def on_menu_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    if not groups:
        await q.edit_message_text(
            f"No groups are currently connected to {cfg.community_name}.",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return
    await q.edit_message_text(
        _render(groups, False), parse_mode="HTML",
        reply_markup=_groups_menu_kb(False),
    )


async def on_menu_groups_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    await q.edit_message_text(
        _render(groups, True), parse_mode="HTML",
        reply_markup=_groups_menu_kb(True),
    )


async def on_menu_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    await q.edit_message_text(
        _render(groups, False), parse_mode="HTML",
        reply_markup=_groups_menu_kb(False),
    )


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

_START_FILTER = (
    filters.Regex(r"^/start$")
    | filters.Regex(r"^/start\s+about$")
    | filters.Regex(r"^/start\s+menu$")
)
_START_PREFIXED = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_FILTER | _START_PREFIXED, cmd_start),
    CallbackQueryHandler(on_menu_back_start,     pattern=r"^menu_back_start$"),
    CallbackQueryHandler(on_menu_groups,         pattern=r"^menu_groups$"),
    CallbackQueryHandler(on_menu_groups_details, pattern=r"^menu_groups_details$"),
    CallbackQueryHandler(on_menu_groups_simple,  pattern=r"^menu_groups_simple$"),
]
