import logging

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import LOG_CHANNEL

logger = logging.getLogger(__name__)


async def log_to_channel(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int | None:
    try:
        msg = await context.bot.send_message(
            chat_id=LOG_CHANNEL,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return msg.message_id
    except TelegramError as exc:
        logger.warning("Failed to log to channel: %s", exc)
        return None
