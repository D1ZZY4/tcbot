"""Feature 18: Federation links — /fedlinks, /links, /fedconfig."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


LINKS_TEXT = (
    "<b>Transsion Core Federation - Official Links and Resources</b>\n\n"
    "Use the buttons below to reach our channels and groups.\n\n"
    "<i>TRAVEL - Transsion Holding's Development. Unofficial independent community.</i>"
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
                    "TRAVEL", url="http://t.me/+S2C_ppFvHlAwMzNl"
                ),
            ],
        ]
    )


async def cmd_fedlinks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    """Re-usable for the start menu Federation Links page."""
    return LINKS_TEXT, _links_keyboard()
