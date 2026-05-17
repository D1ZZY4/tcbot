# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import keyboards

__module_name__ = None

_PRIVACY_MSG = (
    "<b>Privacy & Data</b>\n\n"
    "We keep things simple. Here's what {bot_name} stores about you:\n\n"
    "- <b>User ID & first name</b> — cached when you interact with the bot or a connected group.\n"
    "- <b>Ban records</b> — if you receive a federation ban, the reason and proof are stored alongside it.\n"
    "- <b>Warn & mute records</b> — logged per group for moderation tracking.\n"
    "- <b>Kick logs</b> — recorded for staff reference.\n"
    "- <b>Appeal submissions</b> — your messages and any attachments you send through the appeal system.\n\n"
    "All data is stored securely and is only accessible to {community} staff. "
    "We don't share anything with third parties — ever.\n\n"
    "Tap <b>Privacy Policy</b> below for the full policy."
)

_PRIVACY_POLICY_MSG = (
    "<b>{bot_name} Privacy Policy</b>\n\n"

    "<b>1. What we collect</b>\n"
    "Your Telegram user ID, first name, and username are cached when you interact with {bot_name} "
    "or any connected group. We also store ban records, appeal submissions, warn records, "
    "mute records, and kick logs.\n\n"

    "<b>2. Why we collect it</b>\n"
    "Everything we store is used solely for federation moderation — keeping {community} groups safe "
    "and well-managed. Nothing more.\n\n"

    "<b>3. Who can access it</b>\n"
    "Only {community} staff (admins and the owner) have access to stored data. "
    "No data is shared with third parties under any circumstances.\n\n"

    "<b>4. How long we keep it</b>\n"
    "Ban records are kept indefinitely as part of the federation log. "
    "Cached user data (names, IDs) may be pruned periodically. "
    "Appeal records are kept for reference.\n\n"

    "<b>5. Your rights</b>\n"
    "You can request a review or deletion of your data by reaching out to a {community} admin directly. "
    "We'll handle it as soon as we can.\n\n"

    "<b>6. Contact</b>\n"
    "Reach {community} staff through the main {community} group or via this bot's appeal system."
)


async def on_menu_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    bot_name = ctx.bot.first_name or "This bot"
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _PRIVACY_MSG.format(bot_name=bot_name, community=cfg.community_name), parse_mode="HTML",
            reply_markup=keyboards.privacy_kb(),
        ),
    )


async def on_menu_privacy_policy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    bot_name = ctx.bot.first_name or "This bot"
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _PRIVACY_POLICY_MSG.format(bot_name=bot_name, community=cfg.community_name), parse_mode="HTML",
            reply_markup=keyboards.back_to_privacy_kb(),
        ),
    )


__handlers__ = [
    CallbackQueryHandler(on_menu_privacy,        pattern=r"^menu_privacy$"),
    CallbackQueryHandler(on_menu_privacy_policy, pattern=r"^menu_privacy_policy$"),
]
