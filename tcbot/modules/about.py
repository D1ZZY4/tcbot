# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""About menu callback."""
from __future__ import annotations

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot.modules.helper import keyboards

__module_name__ = None

__about_msg__ = (
    "<b>What is TCF?</b>\n"
    "Transsion Core Federation (TCF) is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "Our main focus is maintaining group security and a conducive environment so members can discuss comfortably.\n"
    "<i>TCF is not an official part of Transsion Holdings. This is strictly an independent community.</i>\n\n"
    "<b>History</b>\n"
    "Established in 2024. Originally named TFI, but it was disbanded due to internal issues. "
    "Shortly after, TCF was formed to continue managing the community with better stability."
)


async def on_menu_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        __about_msg__, parse_mode="HTML",
        reply_markup=keyboards.back_to_start_kb(),
    )


__handlers__ = [
    CallbackQueryHandler(on_menu_about, pattern=r"^menu_about$"),
]
