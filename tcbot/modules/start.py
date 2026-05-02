# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start command and main interactive menu callbacks."""
from __future__ import annotations

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import database as db
from tcbot.modules.about import __about_msg__
from tcbot.modules.helper import keyboards
from tcbot.modules.helper.formatter import code, esc
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = None

_MENU_TEXT = (
    "<b>Hey There! My Name is TC-Bot.</b>\n"
    "I help manage Transsion Core groups, bans, and appeals. "
    "Use the buttons below to learn more or view important links."
)


## ---------------------------------------------------------------------------
## /start command
## ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if arg == "about":
        await msg.reply_text(
            __about_msg__, parse_mode="HTML",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return

    ## appeal<ban_id> deep links are handled by the ConversationHandler in appealing.py
    ## For all other starts (including no arg), show main menu
    await msg.reply_text(
        _MENU_TEXT, parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


## ---------------------------------------------------------------------------
## Menu callbacks
## ---------------------------------------------------------------------------

async def on_menu_back_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _MENU_TEXT, parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


def _groups_text(groups: list[dict], detailed: bool) -> str:
    lines = [f"<b>Connected Groups</b>\n\nCount: {len(groups)}\n"]
    for g in groups:
        if detailed:
            lines.append(f"- {esc(g['title'])} — {code(str(g['chat_id']))}")
        else:
            lines.append(f"- {esc(g['title'])}")
    return "\n".join(lines)


def _groups_menu_kb(detailed: bool) -> InlineKeyboardMarkup:
    toggle = InlineKeyboardButton(
        "Simple" if detailed else "Details",
        callback_data="menu_groups_simple" if detailed else "menu_groups_details",
    )
    back = InlineKeyboardButton("Back", callback_data="menu_back_start")
    return InlineKeyboardMarkup([[toggle], [back]])


async def on_menu_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    groups = await db.groups_db.active_groups()
    if not groups:
        await q.edit_message_text(
            "No groups are currently connected to TCF.",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return
    await q.edit_message_text(
        _groups_text(groups, False), parse_mode="HTML",
        reply_markup=_groups_menu_kb(False),
    )


async def on_menu_groups_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    groups = await db.groups_db.active_groups()
    await q.edit_message_text(
        _groups_text(groups, True), parse_mode="HTML",
        reply_markup=_groups_menu_kb(True),
    )


async def on_menu_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    groups = await db.groups_db.active_groups()
    await q.edit_message_text(
        _groups_text(groups, False), parse_mode="HTML",
        reply_markup=_groups_menu_kb(False),
    )


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

_START_FILTER = (
    filters.Regex(r"^/start$")
    | filters.Regex(r"^/start\s+about$")
)
_START_PREFIXED = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_FILTER | _START_PREFIXED, cmd_start),
    CallbackQueryHandler(on_menu_back_start,         pattern=r"^menu_back_start$"),
    CallbackQueryHandler(on_menu_groups,             pattern=r"^menu_groups$"),
    CallbackQueryHandler(on_menu_groups_details,     pattern=r"^menu_groups_details$"),
    CallbackQueryHandler(on_menu_groups_simple,      pattern=r"^menu_groups_simple$"),
]
