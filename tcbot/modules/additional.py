# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Additional links callback: shows official channels and groups from the start menu."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import CallbackQueryHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import answer_and_edit
from tcbot.modules.helper.rich.block import blocks
from tcbot.utils.i18n import t

__module_name__ = None


# ─────────────────────── Additional Message ─────────────────────── #


def additional_msg(locale: str | None = None) -> str:
    """Render the additional-links menu as real rich paragraphs.

    The catalog text is newline-separated. Without the block converter the
    rich transport sends those newlines inside one HTML string, so Telegram
    folds the heading and the hint into a single line above the buttons.
    """
    return blocks(t("additional.msg.body", locale, community=cfg.community_name))


# ──────────────────────── Callback Handler ──────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_additional_menu(ctx: Ctx) -> None:
    """Render the Additional Info page when the button is tapped."""
    q = ctx.callback_query
    if q is None:
        return

    locale = await locale_for_update(ctx)
    await answer_and_edit(
        q,
        additional_msg(locale),
        reply_markup=await buttons.additional_menu_btn(ctx.bot, locale),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_additional_menu, pattern=r"^additional_menu$"),
]
