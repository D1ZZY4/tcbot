# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Appeal handlers: routes incoming appeals and admin review decisions."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, filters

from tcbot.modules.helper import replies
from tcbot.modules.helper.workflows.appeal_flow import (
    appeal,
    reviewer_locked_out,
    starts_with_appeal_tag,
    text_references_log_message,
)

# * Re-exported for backward-compatible imports.
__all__ = (
    "appeal",
    "reviewer_locked_out",
    "starts_with_appeal_tag",
    "text_references_log_message",
)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Appeal"

__help_text__ = (
    "Submit an appeal for an active federation ban. Staff review with a "
    "<b>12-hour priority window</b> for the banning admin."
)

__help_sections__: list[tuple[str, str]] = [
    (
        "How to start",
        "Tap the <b>Submit Appeal</b> button on your ban notification (sent by the bot in PM), "
        "or use <code>/checkme</code> and tap the appeal button that appears.",
    ),
    (
        replies.SEC_WHO,
        "Anyone with an active federation ban. You can only have one active appeal at a time.",
    ),
    (
        "Where to start",
        "Bot PM only.",
    ),
    (
        "How it works",
        "Once the appeal flow is open, send a single message starting with <code>#appeal</code> "
        "that includes all three of the following sections:\n\n"
        "- <b>Log link</b>: the link to your ban log entry in the federation logs channel\n"
        "- <b>Clarification</b>: your honest explanation of why the ban was issued or was a "
        "mistake\n"
        "- <b>Agreement</b>: your commitment to follow community rules going forward",
    ),
    (
        "Format example",
        "<pre>#appeal\n"
        "Log link: https://t.me/TranssionCoreFederationLogs/123\n"
        "Clarification: I shared links in multiple groups without reading the rules.\n"
        "Agreement: I will follow all community guidelines going forward.</pre>",
    ),
    (
        "What happens next",
        "Your appeal is forwarded to TC admins for review. The admin who issued the original "
        "ban has a <b>12-hour priority window</b> to respond; after that, any admin can act.\n\n"
        "If approved: your ban is lifted immediately across all connected groups.\n"
        "If rejected: your ban remains in place.\n"
        "You will be notified by the bot either way.",
    ),
]


# ──────────────────────────── Handlers ──────────────────────────── #

_APPEAL_START_CMDS = filters.ChatType.PRIVATE & filters.Regex(
    r"^/start\s+appeal_[a-z0-9]{10}$"
)

__handlers__ = [
    appeal.build_handler(_APPEAL_START_CMDS),
    CallbackQueryHandler(appeal.on_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
