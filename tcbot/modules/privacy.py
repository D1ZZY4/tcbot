# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Privacy menu callbacks."""
from __future__ import annotations

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot.modules.helper import keyboards

__module_name__ = None

__privacy_msg__ = (
    "<b>Privacy Information</b>\n\n"
    "The TCF Bot collects and stores the following data:\n"
    "- Your Telegram user ID and first name (cached when you interact with the bot)\n"
    "- Ban records if you are federation-banned\n"
    "- Appeal submissions\n\n"
    "Data is stored securely and is only accessible to TCF staff.\n"
    "No data is shared with third parties."
)

__privacy_policy_msg__ = (
    "<b>TCF Privacy Policy</b>\n\n"
    "1. <b>Data collection:</b> We collect Telegram user IDs, first names, and usernames "
    "only when you interact with a TCF-connected group or this bot.\n\n"
    "2. <b>Data use:</b> Collected data is used solely for federation moderation purposes.\n\n"
    "3. <b>Data retention:</b> Ban records are retained indefinitely. "
    "Member cache data may be pruned periodically.\n\n"
    "4. <b>Your rights:</b> Contact a TCF admin to request data deletion.\n\n"
    "5. <b>Contact:</b> Reach staff via the TCF main group."
)


async def on_menu_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        __privacy_msg__, parse_mode="HTML",
        reply_markup=keyboards.privacy_kb(),
    )


async def on_menu_privacy_policy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        __privacy_policy_msg__, parse_mode="HTML",
        reply_markup=keyboards.back_to_privacy_kb(),
    )


__handlers__ = [
    CallbackQueryHandler(on_menu_privacy,        pattern=r"^menu_privacy$"),
    CallbackQueryHandler(on_menu_privacy_policy, pattern=r"^menu_privacy_policy$"),
]
