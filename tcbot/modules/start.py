# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Start command handler and main-menu callback handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.about import __about_msg__
from tcbot.modules.groups import _render
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.formatter import esc
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CB_LIMIT: int = 15

__module_name__ = None


# ────────────────────────── Start Message ───────────────────────── #

_PRIVATE_START_TEXT = (
    "<b>Hey, I'm {botname}.</b>\n\n"
    f"Federation management assistant for {cfg.community_name}. "
    "I coordinate bans, mutes, kicks, and moderation across all connected groups.\n\n"
    "Use the buttons below to explore."
)

_GROUP_START_TEXT = (
    "<b>Hey, I'm {botname}.</b>\n\n"
    f"Federation management assistant for {cfg.community_name}. "
    "Use /help for the full help menu, or open me in PM for all options."
)


# ──────────────────────── Command Handlers ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to /start in private chats and groups.

    In group context sends a minimal message with a PM deep-link. In private
    context dispatches to the relevant info handler when a deep-link argument is
    present (``ban_<id>``), otherwise shows the full welcome message.
    """
    msg = update.effective_message
    chat = update.effective_chat
    text = (msg.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    botname = esc(ctx.bot.first_name or "")

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


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_back_to_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to the main menu when the Back button is tapped in a sub-menu."""
    q: CallbackQuery = update.callback_query
    botname = esc(ctx.bot.first_name or "")
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _PRIVATE_START_TEXT.format(botname=botname),
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_kb(),
        ),
        return_exceptions=True,
    )


async def _show_groups(q: CallbackQuery, *, detailed: bool) -> None:
    """Shared renderer for all group-menu callbacks."""
    # * Gather q.answer() + DB fetch in parallel; both are independent.
    _, groups = await asyncio.gather(
        q.answer(),
        db.groups_db.active_groups(),
        return_exceptions=True,
    )
    if isinstance(groups, BaseException):
        groups = []
    if not groups:
        await q.edit_message_text(
            f"No groups are currently connected to {cfg.community_name}.",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return
    await q.edit_message_text(
        _render(groups, detailed=detailed),
        parse_mode="HTML",
        reply_markup=keyboards.groups_menu_kb(detailed=detailed),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_menu_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the connected-groups list in simple view from the start menu."""
    await _show_groups(update.callback_query, detailed=False)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_menu_groups_details(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show the connected-groups list with full group IDs visible."""
    await _show_groups(update.callback_query, detailed=True)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_menu_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to simple view of the connected-groups list from the start menu."""
    await _show_groups(update.callback_query, detailed=False)


# ──────────────────────────── Handlers ──────────────────────────── #

_START_CMDS = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_CMDS, cmd_start),
    CallbackQueryHandler(on_back_to_start, pattern=r"^back_to_start$"),
    CallbackQueryHandler(on_menu_groups, pattern=r"^menu_groups$"),
    CallbackQueryHandler(on_menu_groups_details, pattern=r"^menu_groups_details$"),
    CallbackQueryHandler(on_menu_groups_simple, pattern=r"^menu_groups_simple$"),
]
