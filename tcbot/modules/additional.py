# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Additional links callback: shows official channels and groups from the start menu."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

__module_name__ = None

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15


# ─────────────────────── Additional Message ─────────────────────── #

__additional_msg__ = (
    f"{cfg.community_name} <b>Official Links</b>\n\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL, an independent community for collaboration and networking."
)


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_additional_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the Additional Info page when the button is tapped."""
    q: CallbackQuery = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            __additional_msg__,
            parse_mode="HTML",
            reply_markup=keyboards.additional_menu_kb(),
        ),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_additional_menu, pattern=r"^additional_menu$"),
]
