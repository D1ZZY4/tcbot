# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation links handler (PROMPT Feature 18)."""
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..modules import keyboards
from ..modules.messages import M

logger = logging.getLogger(__name__)


async def cmd_fedlinks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the official Transsion Core links."""
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(
        M.LINKS_TEXT,
        reply_markup=keyboards.federation_links(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def get_links_view() -> tuple[str, InlineKeyboardMarkup]:
    """Return the links text and keyboard, re-used by the start menu."""
    return M.LINKS_TEXT, keyboards.federation_links()
