# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Feature 18: Transsion Core links — /tclinks, /links, /tcconfig."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

LINKS_TEXT = (
    "<b>Transsion Core Federation - Official Links</b>\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL - an independent community for collaboration and networking."
)


def _links_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Main Channel", url="https://t.me/TranssionCoreFederation"
                ),
                InlineKeyboardButton(
                    "Discussion Group",
                    url="https://t.me/TranssionCoreFederationGroup",
                ),
            ],
            [
                InlineKeyboardButton(
                    "Logs Channel",
                    url="https://t.me/TranssionCoreFederationLogs",
                ),
                InlineKeyboardButton(
                    "Exec Group", url="https://t.me/+A105pfnCvkhiZWM1"
                ),
            ],
            [
                InlineKeyboardButton(
                    "TRAVEL (Dev Community)",
                    url="http://t.me/+S2C_ppFvHlAwMzNl",
                ),
            ],
        ]
    )


async def cmd_fedlinks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the official Transsion Core links."""
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(
        LINKS_TEXT,
        reply_markup=_links_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def get_links_view() -> tuple[str, InlineKeyboardMarkup]:
    """Return the links text and keyboard for re-use in the start menu."""
    return LINKS_TEXT, _links_keyboard()
