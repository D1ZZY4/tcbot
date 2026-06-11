# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""safe_edit / safe_edit_cb helpers: edit messages in place, suppressing benign Telegram errors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from telegram.error import BadRequest

if TYPE_CHECKING:
    from telegram import CallbackQuery, Message

log = logging.getLogger(__name__)

_IGNORED = {
    "message is not modified",
    "message to edit not found",
    "chat not found",
}


# ──────────────────────── safe_edit helper ──────────────────────── #


async def safe_edit(msg: Message, text: str, **kwargs: Any) -> None:
    """Edit a message via msg.edit_text; swallow harmless not-modified errors."""
    try:
        await msg.edit_text(text, parse_mode="HTML", **kwargs)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("edit failed: %s", e)


async def safe_edit_cb(q: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Edit a callback-query message; swallow harmless not-modified errors.

    Use this whenever a user can re-tap a button that lands them on the same
    content (e.g. a section sub-button while already viewing that section).
    """
    try:
        await q.edit_message_text(text, parse_mode="HTML", **kwargs)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("callback edit failed: %s", e)
