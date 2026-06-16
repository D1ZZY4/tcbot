# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Privacy summary and full privacy-policy menu callbacks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.formatter import bold, esc

if TYPE_CHECKING:
    from telegram import Update

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15

__module_name__ = None


# ──────────────────────── Privacy Messages ──────────────────────── #

_CNAME = esc(cfg.community_name)


def _privacy_msg(botname: str) -> str:
    """Build the data-collection notice for the given bot display name."""
    return (
        f"{bold('Privacy & Data')}\n\n"
        f"We keep things simple. Here's what {botname} stores about you:\n\n"
        f"- {bold('User ID & first name')} - cached when you interact with the bot or a connected group.\n"
        f"- {bold('Ban records')} - if you receive a federation ban, the reason and proof are stored alongside it.\n"
        f"- {bold('Warn & mute records')} - logged per group for moderation tracking.\n"
        f"- {bold('Kick logs')} - recorded for staff reference.\n"
        f"- {bold('Appeal submissions')} - your messages and any attachments you send through the appeal system.\n\n"
        f"All data is stored securely and is only accessible to {_CNAME} staff. "
        "We don't share anything with third parties - ever.\n\n"
        f"Tap {bold('Privacy Policy')} below for the full policy."
    )


def _privacy_policy_msg(botname: str) -> str:
    """Build the full privacy-policy text for the given bot display name."""
    return (
        f"{bold('Privacy Policy')}\n"
        f"{botname}\n"
        f"{bold('1. What we collect')}\n"
        f"Your Telegram user ID, first name, and username are cached when you interact with {botname} "
        f"or any connected group. We also store ban records, appeal submissions, warn records, "
        "mute records, and kick logs.\n\n"
        f"{bold('2. Why we collect it')}\n"
        f"Everything we store is used solely for federation moderation - keeping {_CNAME} groups safe "
        "and well-managed. Nothing more.\n\n"
        f"{bold('3. Who can access it')}\n"
        f"Only {_CNAME} staff (admins and the owner) have access to stored data. "
        "No data is shared with third parties under any circumstances.\n\n"
        f"{bold('4. How long we keep it')}\n"
        "Ban records are kept indefinitely as part of the federation log. "
        "Cached user data (names, IDs) may be pruned periodically. "
        "Appeal records are kept for reference.\n\n"
        f"{bold('5. Your rights')}\n"
        f"You can request a review or deletion of your data by reaching out to a {_CNAME} admin directly. "
        "We'll handle it as soon as we can.\n\n"
        f"{bold('6. Contact')}\n"
        f"Reach {_CNAME} staff through the main {_CNAME} group or via this bot's appeal system."
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the data-collection privacy notice when the Privacy button is tapped."""
    q = update.callback_query
    if q is None:
        return

    botname = esc(ctx.bot.first_name or "This bot")
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _privacy_msg(botname),
            parse_mode="HTML",
            reply_markup=keyboards.privacy_kb(),
        ),
        return_exceptions=True,
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_policy_menu(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render the full privacy policy text when the Privacy Policy button is tapped."""
    q = update.callback_query
    if q is None:
        return

    botname = esc(ctx.bot.first_name or "This bot")
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _privacy_policy_msg(botname),
            parse_mode="HTML",
            reply_markup=keyboards.back_to_privacy_kb(),
        ),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_privacy_menu, pattern=r"^privacy_menu$"),
    CallbackQueryHandler(on_privacy_policy_menu, pattern=r"^privacy_policy_menu$"),
]
