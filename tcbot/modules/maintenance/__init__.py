# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Leaveall and cleanup maintenance commands."""

from __future__ import annotations

from telegram.ext import MessageHandler

from tcbot.modules.helper import replies
from tcbot.modules.maintenance.cleanup import (
    _MEMBERSHIP_CHECK_TIMEOUT,
    _RL_CLEANUP_LIMIT,
    _RL_PERIOD_LONG_S,
    _should_remove,
    cmd_cleanup,
)
from tcbot.modules.maintenance.leave import (
    _RL_LEAVEALL_LIMIT,
    _RL_PERIOD_BULK_S,
    _leave_one,
    _LeaveResult,
    cmd_leaveall,
)
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import build_prefixed_filters

__all__ = [
    "_CLEANUP_CMDS",
    "_LEAVEALL_CMDS",
    "_MEMBERSHIP_CHECK_TIMEOUT",
    "_RL_CLEANUP_LIMIT",
    "_RL_LEAVEALL_LIMIT",
    "_RL_PERIOD_BULK_S",
    "_RL_PERIOD_LONG_S",
    "_LeaveResult",
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "_leave_one",
    "_should_remove",
    "cmd_cleanup",
    "cmd_leaveall",
    "get_help",
]


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Maintenance"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("maintenance.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("maintenance.help.commands.body", locale),
        ),
        replies.who_section(
            f"{bold('/leaveall')}: {replies.perm_founder_only(locale, plain=False)}\n"
            f"{bold('/cleanup')}: {replies.perm_staff_only(locale, plain=False)}",
            locale,
        ),
        replies.where_section(replies.context_exec_or_group(locale), locale),
        (
            "/leaveall",
            t("maintenance.help.leaveall.body", locale),
        ),
        (
            "/cleanup",
            t("maintenance.help.cleanup.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("maintenance.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────────── Handlers ──────────────────────────── #

_LEAVEALL_CMDS = (
    build_prefixed_filters("leaveall")
    | build_prefixed_filters("exitall")
    | build_prefixed_filters("tcleave")
)
_CLEANUP_CMDS = (
    build_prefixed_filters("cleanup")
    | build_prefixed_filters("tcclean")
    | build_prefixed_filters("tcc")
)


__handlers__ = [
    MessageHandler(_LEAVEALL_CMDS, cmd_leaveall),
    MessageHandler(_CLEANUP_CMDS, cmd_cleanup),
]
