# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About callback: shows the community description from the start menu."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from telegram import Update

__module_name__ = None

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15


# ────────────────────────── About Message ───────────────────────── #

# * Raw community name; the template escapes it at render time.


def about_msg(locale: str | None = None) -> str:
    """Render the About page in the given locale."""
    cname = cfg.community_name
    disc = Safe(t("about.page.disclaimer_text", locale, community=cname))
    return (
        f"{t('about.page.title', locale, title=Safe(bold(cname)))}\n\n"
        f"{t('about.page.intro', locale)}\n\n"
        f"{t('about.page.how_title', locale)}\n"
        f"{t('about.page.how_body', locale)}\n\n"
        f"{t('about.page.history_title', locale)}\n"
        f"{t('about.page.history_body', locale, community=cname)}\n\n"
        f"{t('about.page.disclaimer', locale, disc=disc)}"
    )


__about_msg__ = about_msg()


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_about_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the About page when the About button is tapped."""
    q = update.callback_query
    if q is None:
        return

    locale = await locale_for_update(update)
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            about_msg(locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.back_to_start_kb(locale),
        ),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_about_menu, pattern=r"^about_menu$"),
]
