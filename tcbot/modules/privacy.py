# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Privacy summary and full privacy-policy menu callbacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.formatter import esc

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15

__module_name__ = None


# ──────────────────────── Privacy Messages ──────────────────────── #

_PRIVACY_MSG = (
    "<b>Privacy & Data</b>\n\n"
    "We keep things simple. Here's what {botname} stores about you:\n\n"
    "- <b>User ID & first name</b> - cached when you interact with the bot or a connected group.\n"
    "- <b>Ban records</b> - if you receive a federation ban, the reason and proof are stored alongside it.\n"
    "- <b>Warn & mute records</b> - logged per group for moderation tracking.\n"
    "- <b>Kick logs</b> - recorded for staff reference.\n"
    "- <b>Appeal submissions</b> - your messages and any attachments you send through the appeal system.\n\n"
    f"All data is stored securely and is only accessible to {cfg.community_name} staff. "
    "We don't share anything with third parties - ever.\n\n"
    "Tap <b>Privacy Policy</b> below for the full policy."
)

_PRIVACY_POLICY_MSG = (
    "<b>Privacy Policy</b>\n"
    "{botname}\n"
    "<b>1. What we collect</b>\n"
    "Your Telegram user ID, first name, and username are cached when you interact with {botname} "
    "or any connected group. We also store ban records, appeal submissions, warn records, "
    "mute records, and kick logs.\n\n"
    "<b>2. Why we collect it</b>\n"
    f"Everything we store is used solely for federation moderation - keeping {cfg.community_name} groups safe "
    "and well-managed. Nothing more.\n\n"
    "<b>3. Who can access it</b>\n"
    f"Only {cfg.community_name} staff (admins and the owner) have access to stored data. "
    "No data is shared with third parties under any circumstances.\n\n"
    "<b>4. How long we keep it</b>\n"
    "Ban records are kept indefinitely as part of the federation log. "
    "Cached user data (names, IDs) may be pruned periodically. "
    "Appeal records are kept for reference.\n\n"
    "<b>5. Your rights</b>\n"
    f"You can request a review or deletion of your data by reaching out to a {cfg.community_name} admin directly. "
    "We'll handle it as soon as we can.\n\n"
    "<b>6. Contact</b>\n"
    f"Reach {cfg.community_name} staff through the main {cfg.community_name} group or via this bot's appeal system."
)


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the data-collection privacy notice when the Privacy button is tapped."""
    q: CallbackQuery = update.callback_query
    botname = esc(ctx.bot.first_name or "This bot")
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_MSG.format(botname=botname),
        parse_mode="HTML",
        reply_markup=keyboards.privacy_kb(),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_policy_menu(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render the full privacy policy text when the Privacy Policy button is tapped."""
    q: CallbackQuery = update.callback_query
    botname = esc(ctx.bot.first_name or "This bot")
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_POLICY_MSG.format(botname=botname),
        parse_mode="HTML",
        reply_markup=keyboards.back_to_privacy_kb(),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_privacy_menu, pattern=r"^privacy_menu$"),
    CallbackQueryHandler(on_privacy_policy_menu, pattern=r"^privacy_policy_menu$"),
]
