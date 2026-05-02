# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Post TCF community links."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Links"
__help_text__ = (
    "<code>/tclinks</code> – show TCF community links.\n"
    "Aliases: <code>/links</code>, <code>/tcconfig</code>"
)

_LINKS_TEXT = (
    "<b>Transsion Core Federation - Official Links</b>\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL - an independent community for collaboration and networking."
)


def _links_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Main Channel", url="https://t.me/TranssionCoreFederation"),
            InlineKeyboardButton("Discussion Group", url="https://t.me/TranssionCoreFederationGroup"),
        ],
        [
            InlineKeyboardButton("Logs Channel", url="https://t.me/TranssionCoreFederationLogs"),
            InlineKeyboardButton("Exec Group", url="https://t.me/+A105pfnCvkhiZWM1"),
        ],
        [
            InlineKeyboardButton("TRAVEL (Dev Community)", url="http://t.me/+S2C_ppFvHlAwMzNl"),
        ],
    ])


async def cmd_tclinks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        _LINKS_TEXT,
        parse_mode="HTML",
        reply_markup=_links_kb(),
    )


## Spec aliases: /tclinks, /links, /tcconfig
_LINKS_FILTER = (
    build_prefixed_filters("tclinks")
    | build_prefixed_filters("links")
    | build_prefixed_filters("tcconfig")
)

__handlers__ = [MessageHandler(_LINKS_FILTER, cmd_tclinks)]
