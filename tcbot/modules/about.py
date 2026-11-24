# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About callbacks: index and section pages from the start menu."""

from __future__ import annotations

from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import CallbackQueryHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    about_msg,
    about_section_labels,
    about_section_msg,
    answer_and_edit,
)
from tcbot.modules.helper.rich.edit import callback_text_of
from tcbot.utils.i18n import t

__module_name__ = None

_SECTION_PREFIX = "about_section_"
_SECTION_COUNT = len(about_section_labels("en-US"))


# ──────────────────────── Callback Handler ────────────────────────


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_about_menu(ctx: Ctx) -> None:
    """Render the About section index when the About button is tapped."""
    q = ctx.callback_query
    if q is None:
        return

    locale = await locale_for_update(ctx)
    await answer_and_edit(
        q,
        about_msg(locale),
        reply_markup=buttons.about_sections_btn(about_section_labels(locale), locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_about_section(ctx: Ctx) -> None:
    """Render one About section page."""
    q = ctx.callback_query
    if q is None:
        return
    data = callback_text_of(q)
    if not data:
        await q.answer()
        return

    locale = await locale_for_update(ctx)
    try:
        idx = int(data[len(_SECTION_PREFIX) :])
    except ValueError:
        await q.answer(
            t("about.error.invalid_section", locale, plain=True), show_alert=True
        )
        return
    if idx < 0 or idx >= _SECTION_COUNT:
        await q.answer(t("about.error.not_found", locale, plain=True), show_alert=True)
        return

    await answer_and_edit(
        q,
        about_section_msg(idx, locale),
        reply_markup=buttons.back_to_about_btn(locale),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_about_menu, pattern=r"^about_menu$"),
    CallbackQueryHandler(on_about_section, pattern=rf"^{_SECTION_PREFIX}\d+$"),
]
