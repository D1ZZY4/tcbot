# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards

__module_name__ = None


# ────────────────────────── About Message ───────────────────────── #

__about_msg__ = (
    f"<b>What is</b> {cfg.community_name}?\n"
    f"{cfg.community_name} is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "Our main focus is maintaining group security and a conducive environment so members can discuss comfortably.\n\n"
    "<b>History</b>\n"
    "Established in 2024. Originally named TFI, but it was disbanded due to internal issues. "
    f"Shortly after, {cfg.community_name} was formed to continue managing the community with better stability.\n\n"
    f"{cfg.community_name} <i>is not an official part of Transsion Holdings. This is strictly an independent community.</i>"
)


# ──────────────────────── Callback Handler ──────────────────────── #

@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_about_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            __about_msg__, parse_mode="HTML",
            reply_markup=keyboards.back_to_start_kb(),
        ),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_about_menu, pattern=r"^about_menu$"),
]
