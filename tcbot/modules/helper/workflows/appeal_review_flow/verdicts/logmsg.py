# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal log edit helper for staff verdicts."""

from __future__ import annotations

from telegram import Bot

from tcbot.utils.logger import get_logger

log = get_logger(__name__)


async def _update_or_send_log(
    bot: Bot,
    lc: int,
    lt: int | None,
    msg_id: int | None,
    text: str,
) -> None:
    """Edit the existing appeal log message, or post a new one as fallback."""
    if msg_id:
        try:
            await bot.edit_message_text(
                text, chat_id=lc, message_id=msg_id, parse_mode="MarkdownV2"
            )
            return
        except Exception as exc:
            log.warning("Could not edit appeal submitted log: %s", exc)
    try:
        await bot.send_message(lc, text, parse_mode="MarkdownV2", message_thread_id=lt)
    except Exception as exc:
        log.debug("Could not send appeal submitted log: %s", exc)
