# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""safe_edit helper – edits a message in place, suppressing benign Telegram errors."""

from __future__ import annotations

import logging

from telegram import Message
from telegram.error import BadRequest

log = logging.getLogger(__name__)

_IGNORED = {
    "message is not modified",
    "message to edit not found",
    "chat not found",
}


# ──────────────────────── safe_edit helper ──────────────────────── #


async def safe_edit(msg: Message, text: str, **kwargs) -> None:
    try:
        await msg.edit_text(text, parse_mode="HTML", **kwargs)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("edit failed: %s", e)
