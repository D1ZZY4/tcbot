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
)
from tcbot.utils.formatter import bold, pre
from tcbot.utils.i18n import Safe, t

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Appeal"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    window = Safe(bold(t("appeals.help.window", locale, hours=LOCK_HOURS, plain=True)))
    overview = t("appeals.help.overview", locale, window=window)
    sections: list[tuple[str, str]] = [
        (
            t("appeals.help.start.title", locale, plain=True),
            t("appeals.help.start.body", locale),
        ),
        replies.who_section(t("appeals.help.who.body", locale), locale),
        (
            t("appeals.help.where.title", locale, plain=True),
            t("appeals.help.where.body", locale),
        ),
        (
            t("appeals.help.how.title", locale, plain=True),
            t("appeals.help.how.body", locale),
        ),
        (
            t("appeals.help.format.title", locale, plain=True),
            pre(t("appeals.help.format.body", locale, plain=True)),
        ),
        (
            t("appeals.help.next.title", locale, plain=True),
            t("appeals.help.next.body", locale, window=window),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────────── Handlers ──────────────────────────── #

_APPEAL_START_CMDS = filters.ChatType.PRIVATE & filters.Regex(
    r"^/start\s+appeal_[a-z0-9]{10}$"
)

__handlers__ = [
    appeal.build_handler(_APPEAL_START_CMDS),
    CallbackQueryHandler(appeal.on_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
