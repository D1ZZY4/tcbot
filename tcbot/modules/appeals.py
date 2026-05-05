# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Appeal system — pure guard functions and PTB module registration
##
## Pure functions (no Telegram I/O) live at the top so they remain fully
## unit-testable. Module metadata (__module_name__, __help_text__, __handlers__)
## follows at the bottom, wiring everything into the bot.
from __future__ import annotations

import re
from datetime import datetime, timedelta

from telegram.ext import CallbackQueryHandler

from tcbot.modules.helper.parse_link import utcnow
from tcbot.modules.helper.workflows.appeal_flow import build_handler, on_appeal_decision

_LOCK_WINDOW = timedelta(hours=12)


## ── Pure guard functions ─────────────────────────────────────────────────────


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text (stripped) starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone integer token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """Check whether reviewer_id is blocked from reviewing within the lock window.

    Returns False immediately when metadata is absent or reviewer is the
    original banning admin (they may always review their own bans).
    Returns True only if elapsed < LOCK_WINDOW and reviewer is a different admin.
    """
    if review_timestamp is None or ban_admin_id is None:
        return False
    if reviewer_id == ban_admin_id:
        return False
    ts = review_timestamp
    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    elapsed = utcnow() - ts
    return elapsed < _LOCK_WINDOW


def now() -> datetime:
    """Return the current UTC datetime (alias for utcnow, patchable in tests)."""
    return utcnow()


## ── PTB module registration ──────────────────────────────────────────────────

__module_name__ = "Appeal"

__help_text__ = (
    "<b>How to start an appeal</b>\n"
    "Tap the <b>Submit Appeal</b> button on your ban log message, or open the bot in PM "
    "and use the deep link from your ban notification.\n\n"

    "<b>Who can use it</b>\n"
    "Anyone with an active federation ban.\n\n"

    "<b>Where to start</b>\n"
    "Bot PM only.\n\n"

    "<b>How it works</b>\n"
    "Once you open the appeal flow, reply with a message that starts with <code>#appeal</code> "
    "and includes the following:\n\n"
    "- <b>Log link:</b> the link to your ban log (from @TranssionCoreFederationLogs)\n"
    "- <b>Clarification:</b> your honest explanation of what happened\n"
    "- <b>Agreement:</b> your commitment not to repeat the violation\n\n"
    "<b>Format example:</b>\n"
    "<pre>#appeal\n"
    "Log link: https://t.me/TranssionCoreFederationLogs/123\n"
    "Clarification: I spammed links without knowing the rules.\n"
    "Agreement: I will follow all community rules going forward.</pre>\n\n"

    "<b>What happens next</b>\n"
    "Your appeal is forwarded to TC admins for review. The admin who issued the ban has "
    "<b>12 hours</b> to respond. After that, any admin can approve or reject it.\n"
    "If approved → ban is lifted immediately.\n"
    "If rejected → ban stays. You'll be notified either way."
)

__handlers__ = [
    build_handler(),
    CallbackQueryHandler(on_appeal_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
