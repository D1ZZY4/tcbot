# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Additional links callback: shows official channels and groups from the start menu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import answer_and_edit
from tcbot.utils.i18n import t

if TYPE_CHECKING:
    from telegram import Update

__module_name__ = None

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15


# ─────────────────────── Additional Message ─────────────────────── #


def additional_msg(locale: str | None = None) -> str:
    """Render the additional-links menu text."""
    return t("additional.msg.body", locale, community=cfg.community_name)


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_additional_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the Additional Info page when the button is tapped."""
    q = update.callback_query
    if q is None:
        return

    locale = await locale_for_update(update)
    await answer_and_edit(
        q,
        additional_msg(locale),
        reply_markup=keyboards.additional_menu_kb(locale),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_additional_menu, pattern=r"^additional_menu$"),
]
