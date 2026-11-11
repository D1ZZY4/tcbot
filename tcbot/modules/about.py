# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About callback: shows the community description from the start menu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import about_msg, answer_and_edit

if TYPE_CHECKING:
    from telegram import Update

__module_name__ = None


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_about_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the About page when the About button is tapped."""
    q = update.callback_query
    if q is None:
        return

    locale = await locale_for_update(update)
    await answer_and_edit(
        q,
        about_msg(locale),
        reply_markup=keyboards.back_to_start_kb(locale),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_about_menu, pattern=r"^about_menu$"),
]
