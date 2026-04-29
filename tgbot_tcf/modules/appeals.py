# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Appeal-flow business logic.

Responsibilities split with :mod:`tgbot_tcf.handlers.appeal`:

* The handler owns the in-memory session map (per ``user_id``) and the
  Telegram event plumbing.
* This module owns the parsing rules (``#appeal`` header + log-link match),
  the 12-hour reviewer rule, the ban-record write paths, and the
  Telegram-side posting of the appeal text and admin review message.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional, Tuple

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import APPEAL_DISCUSSION_TOPIC, APPEAL_TOPIC, MAIN_GROUP
from ..database import bans_repo
from ..utils.format import topic_link, utcnow
from . import keyboards, log_templates

logger = logging.getLogger(__name__)

_APPEAL_HEADER_RE = re.compile(r"^\s*#appeal\b", re.IGNORECASE)


# --------------------------------------------------------- parsing helpers

def starts_with_appeal_tag(text: str) -> bool:
    """Return ``True`` when the text begins (after whitespace) with ``#appeal``."""
    return bool(_APPEAL_HEADER_RE.match(text or ""))


def text_references_log_message(text: str, log_message_id: int) -> bool:
    """The PROMPT requires the appeal to reference the user's own log message."""
    return bool(re.search(rf"/{log_message_id}(?:[^0-9]|$)", text or ""))


# ---------------------------------------------------------- reviewer rules

def reviewer_locked_out(
    *,
    review_timestamp: Optional[datetime],
    ban_admin_id: Optional[int],
    reviewer_id: int,
    window_seconds: int = 12 * 3600,
) -> bool:
    """Implement the 12-hour exclusivity rule for the original banning admin."""
    if not review_timestamp or not ban_admin_id:
        return False
    elapsed = (utcnow() - review_timestamp).total_seconds()
    return elapsed < window_seconds and reviewer_id != ban_admin_id


# ---------------------------------------------------------------- posting

async def post_appeal_text(
    context: ContextTypes.DEFAULT_TYPE, text: str
) -> Optional[Tuple[int, str]]:
    """Send the appeal body to the appeal topic. Returns (msg_id, link)."""
    try:
        appeal_msg = await context.bot.send_message(
            chat_id=MAIN_GROUP,
            message_thread_id=APPEAL_TOPIC,
            text=text,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.exception("Failed to post appeal: %s", exc)
        return None
    link = topic_link(MAIN_GROUP, appeal_msg.message_id, APPEAL_TOPIC)
    return appeal_msg.message_id, link


async def post_review_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    user_name: str,
    ban_id: str,
    appeal_link: str,
    submitted_at: datetime,
) -> Optional[int]:
    """Send the Approve / Reject review message to the discussion topic."""
    try:
        msg = await context.bot.send_message(
            chat_id=MAIN_GROUP,
            message_thread_id=APPEAL_DISCUSSION_TOPIC,
            text=log_templates.appeal_review_message(
                user_id=user_id,
                user_name=user_name,
                ban_id=ban_id,
                appeal_link=appeal_link,
                submitted_at=submitted_at,
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.appeal_review(ban_id),
            disable_web_page_preview=True,
        )
        return msg.message_id
    except TelegramError as exc:
        logger.exception("Failed to send review message: %s", exc)
        return None


# --------------------------------------------------------------- DB writes

async def attach_review_metadata(
    *, ban_id: str, review_message_id: int, when: datetime
) -> None:
    await bans_repo.attach_review(
        ban_id=ban_id,
        review_message_id=review_message_id,
        review_timestamp=when,
    )


async def mark_resolved_inactive(ban_id: str) -> None:
    await bans_repo.deactivate(ban_id)


def now() -> datetime:
    return utcnow()
