# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start command and main interactive menu callbacks."""
from __future__ import annotations

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import cfg, database as db
from tcbot.modules.helper import keyboards
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = None

_PAGE_SIZE = 10

_MENU_TEXT = (
    "<b>Hey There! My Name is TC-Bot.</b>\n"
    "I help manage Transsion Core groups, bans, and appeals. "
    "Use the buttons below to learn more or view important links."
)

_ABOUT_TEXT = (
    "<b>What is TCF?</b>\n"
    "Transsion Core Federation (TCF) is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "Our main focus is maintaining group security and a conducive environment so members can discuss comfortably.\n"
    "<i>TCF is not an official part of Transsion Holdings. This is strictly an independent community.</i>\n\n"
    "<b>History</b>\n"
    "Established in 2024. Originally named TFI, but it was disbanded due to internal issues. "
    "Shortly after, TCF was formed to continue managing the community with better stability."
)

_PRIVACY_TEXT = (
    "<b>Privacy Information</b>\n\n"
    "The TCF Bot collects and stores the following data:\n"
    "- Your Telegram user ID and first name (cached when you interact with the bot)\n"
    "- Ban records if you are federation-banned\n"
    "- Appeal submissions\n\n"
    "Data is stored securely and is only accessible to TCF staff.\n"
    "No data is shared with third parties."
)

_PRIVACY_POLICY_TEXT = (
    "<b>TCF Privacy Policy</b>\n\n"
    "1. <b>Data collection:</b> We collect Telegram user IDs, first names, and usernames "
    "only when you interact with a TCF-connected group or this bot.\n\n"
    "2. <b>Data use:</b> Collected data is used solely for federation moderation purposes.\n\n"
    "3. <b>Data retention:</b> Ban records are retained indefinitely. "
    "Member cache data may be pruned periodically.\n\n"
    "4. <b>Your rights:</b> Contact a TCF admin to request data deletion.\n\n"
    "5. <b>Contact:</b> Reach staff via the TCF main group."
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
            _ABOUT_TEXT, parse_mode="HTML",
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


async def on_menu_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _ABOUT_TEXT, parse_mode="HTML",
        reply_markup=keyboards.back_to_start_kb(),
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



async def on_menu_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_TEXT, parse_mode="HTML",
        reply_markup=keyboards.privacy_kb(),
    )


async def on_menu_privacy_policy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_POLICY_TEXT, parse_mode="HTML",
        reply_markup=keyboards.back_to_privacy_kb(),
    )


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

## /start (with or without args), but NOT appeal_ deep links (handled by ConversationHandler)
_START_FILTER = (
    filters.Regex(r"^/start$")
    | filters.Regex(r"^/start\s+about$")
    ## Don't capture appeal_ here – that goes to ConversationHandler in appealing.py
)
## Also accept prefixed variants except for appeal deep link
_START_PREFIXED = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_FILTER | _START_PREFIXED, cmd_start),
    ## Menu callbacks
    CallbackQueryHandler(on_menu_back_start, pattern=r"^menu_back_start$"),
    CallbackQueryHandler(on_menu_about, pattern=r"^menu_about$"),
    CallbackQueryHandler(on_menu_groups,         pattern=r"^menu_groups$"),
    CallbackQueryHandler(on_menu_groups_details, pattern=r"^menu_groups_details$"),
    CallbackQueryHandler(on_menu_groups_simple,  pattern=r"^menu_groups_simple$"),

    CallbackQueryHandler(on_menu_privacy, pattern=r"^menu_privacy$"),
    CallbackQueryHandler(on_menu_privacy_policy, pattern=r"^menu_privacy_policy$"),
]
