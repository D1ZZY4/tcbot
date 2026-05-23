# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import re

from telegram.ext import CallbackQueryHandler, filters

from tcbot.modules.helper.workflows.appeal_flow import (
    appeal,
)
from tcbot.modules.helper.workflows.appeal_flow import (
    reviewer_locked_out as _reviewer_locked_out,
)

reviewer_locked_out = _reviewer_locked_out


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Appeal"

__help_text__ = (
    "<b>How to start an appeal</b>\n"
    "Tap the <b>Submit Appeal</b> button on your ban notification (sent by the bot in PM), "
    "or use <code>/checkme</code> and tap the appeal button that appears.\n\n"
    "<b>Who can use it</b>\n"
    "Anyone with an active federation ban. You can only have one active appeal at a time.\n\n"
    "<b>Where to start</b>\n"
    "Bot PM only.\n\n"
    "<b>How it works</b>\n"
    "Once the appeal flow is open, send a single message starting with <code>#appeal</code> "
    "that includes all three of the following sections:\n\n"
    "- <b>Log link:</b> the link to your ban log entry in the federation logs channel\n"
    "- <b>Clarification:</b> your honest explanation of why the ban was issued or was a mistake\n"
    "- <b>Agreement:</b> your commitment to follow community rules going forward\n\n"
    "<b>Format example:</b>\n"
    "<pre>#appeal\n"
    "Log link: https://t.me/TranssionCoreFederationLogs/123\n"
    "Clarification: I shared links in multiple groups without reading the rules.\n"
    "Agreement: I will follow all community guidelines going forward.</pre>\n\n"
    "<b>What happens next</b>\n"
    "Your appeal is forwarded to TC admins for review. The admin who issued the original ban "
    "has a <b>12-hour priority window</b> to respond - after that, any admin can act on it.\n\n"
    "If approved → your ban is lifted immediately across all connected groups.\n"
    "If rejected → your ban remains in place.\n"
    "You will be notified by the bot either way."
)


# ──────────────────────────── Functions ─────────────────────────── #


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text (stripped) starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone integer token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


# ───────────────────────── Handlers ─────────────────────────────── #

_APPEAL_START_CMDS = filters.ChatType.PRIVATE & filters.Regex(
    r"^/start\s+appeal_[a-z0-9]{10}$"
)

__handlers__ = [
    appeal.build_handler(_APPEAL_START_CMDS),
    CallbackQueryHandler(appeal.on_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
