# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators

__module_name__ = None


# ─────────────────────── Additional Message ─────────────────────── #

__additional_msg__ = (
    f"{cfg.community_name} <b>Official Links</b>\n\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL, an independent community for collaboration and networking."
)


def _additional_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Main Channel", url="https://t.me/TranssionCoreFederation"
                ),
                InlineKeyboardButton(
                    "Discussion Group", url="https://t.me/TranssionCoreFederationGroup"
                ),
            ],
            [
                InlineKeyboardButton(
                    "Logs Channel", url="https://t.me/TranssionCoreFederationLogs"
                ),
                InlineKeyboardButton(
                    "Exec Group", url="https://t.me/+A105pfnCvkhiZWM1"
                ),
            ],
            [
                InlineKeyboardButton(
                    "TRAVEL - Transsion Development (Community)",
                    url="http://t.me/+S2C_ppFvHlAwMzNl",
                ),
            ],
            [InlineKeyboardButton("« Back", callback_data="back_to_start")],
        ]
    )


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_additional_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            __additional_msg__,
            parse_mode="HTML",
            reply_markup=_additional_kb(),
        ),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_additional_menu, pattern=r"^additional_menu$"),
]
