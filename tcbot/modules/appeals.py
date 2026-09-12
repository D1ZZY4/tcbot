# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal handlers: routes incoming appeals and admin review decisions."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, filters

from tcbot.modules.helper import replies
from tcbot.modules.helper.workflows.appeal_flow import (
    LOCK_HOURS,
    appeal,
    reviewer_locked_out,
    starts_with_appeal_tag,
    text_references_log_message,
)
from tcbot.utils.formatter import bold, pre
from tcbot.utils.i18n import Safe, t

# * Re-exported for backward-compatible imports.
__all__ = (
    "appeal",
    "reviewer_locked_out",
    "starts_with_appeal_tag",
    "text_references_log_message",
)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Appeal"

__help_text__ = t(
    "appeals.help.overview",
    window=Safe(bold(f"{LOCK_HOURS}-hour priority window")),
)

__help_sections__: list[tuple[str, str]] = [
    (
        "How to start",
        t("appeals.help.start.body"),
    ),
    replies.who_section(t("appeals.help.who.body")),
    (
        "Where to start",
        t("appeals.help.where.body"),
    ),
    (
        "How it works",
        t("appeals.help.how.body"),
    ),
    (
        "Format example",
        pre(t("appeals.help.format.body", plain=True)),
    ),
    (
        "What happens next",
        t(
            "appeals.help.next.body",
            window=Safe(bold(f"{LOCK_HOURS}-hour priority window")),
        ),
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


# ──────────────────────────── Handlers ──────────────────────────── #

_APPEAL_START_CMDS = filters.ChatType.PRIVATE & filters.Regex(
    r"^/start\s+appeal_[a-z0-9]{10}$"
)

__handlers__ = [
    appeal.build_handler(_APPEAL_START_CMDS),
    CallbackQueryHandler(appeal.on_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
