# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg

__module_name__ = None

__additional_msg__ = (
    f"<b>{cfg.community_name} | Official Links</b>\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL, an independent community for collaboration and networking."
)


def _additional_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Main Channel",     url="https://t.me/TranssionCoreFederation"),
            InlineKeyboardButton("Discussion Group", url="https://t.me/TranssionCoreFederationGroup"),
        ],
        [
            InlineKeyboardButton("Logs Channel", url="https://t.me/TranssionCoreFederationLogs"),
            InlineKeyboardButton("Exec Group",   url="https://t.me/+A105pfnCvkhiZWM1"),
        ],
        [
            InlineKeyboardButton("TRAVEL (Dev Community)", url="http://t.me/+S2C_ppFvHlAwMzNl"),
        ],
        [InlineKeyboardButton("« Back", callback_data="menu_back_start")],
    ])


async def on_menu_additional(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            __additional_msg__,
            parse_mode="HTML",
            reply_markup=_additional_kb(),
        ),
    )


__handlers__ = [
    CallbackQueryHandler(on_menu_additional, pattern=r"^menu_additional$"),
]
