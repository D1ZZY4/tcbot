# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Start command handler and main-menu callback handlers."""

from __future__ import annotations

import asyncio
import logging

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.about import __about_msg__
from tcbot.modules.groups import _render
from tcbot.modules.helper import decorators, keyboards
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = None


# ────────────────────────── Start Message ───────────────────────── #

_PRIVATE_START_TEXT = (
    "<b>Hey! I'm {botname}. 👋</b>\n\n"
    f"I am an assistant of {cfg.community_name} to manage the groups connected to me centrally\n"
    "Use the buttons below to explore."
)

_GROUP_START_TEXT = (
    "<b>Hey! I'm {botname}. 👋</b>\n\n"
    f"I am an assistant of {cfg.community_name} to manage the groups connected to me centrally\n"
    "Use /help for all help menu, or open me in PM for the full menu."
)


# ──────────────────────── Command Handlers ──────────────────────── #


@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    text = (msg.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    botname = ctx.bot.first_name

    # * Group / supergroup context - send a minimal message with PM link
    if chat.type in ("group", "supergroup", "forum"):
        bot_username = ctx.bot.username or ""
        await msg.reply_text(
            _GROUP_START_TEXT.format(botname=botname),
            parse_mode="HTML",
            reply_markup=keyboards.group_start_kb(bot_username),
        )
        return

    # * PM context below
    if arg == "about":
        await msg.reply_text(
            __about_msg__,
            parse_mode="HTML",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return

    # * appeal<ban_id> deep links are handled by the ConversationHandler in appeals.py
    await msg.reply_text(
        _PRIVATE_START_TEXT.format(botname=botname),
        parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_back_to_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    botname = ctx.bot.first_name
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _PRIVATE_START_TEXT.format(botname=botname),
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_kb(),
        ),
    )


async def _show_groups(q: CallbackQuery, detailed: bool) -> None:
    """Shared renderer for all group-menu callbacks."""
    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    if not groups:
        await q.edit_message_text(
            f"No groups are currently connected to {cfg.community_name}.",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return
    await q.edit_message_text(
        _render(groups, detailed),
        parse_mode="HTML",
        reply_markup=keyboards.groups_menu_kb(detailed),
    )


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_menu_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_groups(update.callback_query, False)


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_menu_groups_details(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    await _show_groups(update.callback_query, True)


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_menu_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_groups(update.callback_query, False)


# ──────────────────────────── Handlers ──────────────────────────── #

_START_CMDS = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_CMDS, cmd_start),
    CallbackQueryHandler(on_back_to_start, pattern=r"^back_to_start$"),
    CallbackQueryHandler(on_menu_groups, pattern=r"^menu_groups$"),
    CallbackQueryHandler(on_menu_groups_details, pattern=r"^menu_groups_details$"),
    CallbackQueryHandler(on_menu_groups_simple, pattern=r"^menu_groups_simple$"),
]
