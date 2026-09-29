# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn, unwarn, warnlist, and resetwarns command handlers."""

from __future__ import annotations

from telegram.ext import MessageHandler

from tcbot import cfg
from tcbot.modules.helper import replies
from tcbot.modules.helper.workflows.warning_flow import warn_conversation
from tcbot.modules.warnings.manage import cmd_resetwarns, cmd_unwarn, cmd_warnlist
from tcbot.modules.warnings.warn import (
    _RL_CMD_PERIOD_S,
    _RL_PERIOD_S,
    _RL_READ_LIMIT,
    _RL_WARN_LIMIT,
    _WARN_KEYS,
    cmd_warn_entry,
)
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters

__all__ = [
    "_RESET_CMDS",
    "_RL_CMD_PERIOD_S",
    "_RL_PERIOD_S",
    "_RL_READ_LIMIT",
    "_RL_WARN_LIMIT",
    "_UNWARN_CMDS",
    "_WARNLIST_CMDS",
    "_WARN_CMDS",
    "_WARN_ESCAPE_CMDS",
    "_WARN_KEYS",
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "cmd_resetwarns",
    "cmd_unwarn",
    "cmd_warn_entry",
    "cmd_warnlist",
    "get_help",
]


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Warnings"


def _warn_limit_label(locale: str | None = None) -> Safe:
    """Pre-formatted warn-limit fragment for help placeholders.

    Markup around a dynamic value cannot come from TOML, so it is
    composed here per locale.
    """
    return Safe(
        bold(f"{cfg.warn_limit} {t('warnings.help.limit_noun', locale, plain=True)}")
    )


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("warnings.help.overview", locale, limit=_warn_limit_label(locale))
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("warnings.help.commands.body", locale),
        ),
        replies.who_section(t("warnings.help.who.body", locale), locale),
        replies.where_section(replies.where_connected_group(locale), locale),
        (
            replies.sec_what(locale),
            t("warnings.help.what.body", locale, limit=_warn_limit_label(locale)),
        ),
        (
            replies.sec_flow(locale),
            t("warnings.help.flow.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("warnings.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────────── Handlers ──────────────────────────── #

_WARN_CMDS = build_prefixed_filters("tcwarn") | build_prefixed_filters("tcw")
_UNWARN_CMDS = build_prefixed_filters("tcunwarn") | build_prefixed_filters("tcunw")
_WARNLIST_CMDS = build_prefixed_filters("warns") | build_prefixed_filters("warnlist")
_RESET_CMDS = build_prefixed_filters("resetwarns") | build_prefixed_filters(
    "clearwarns"
)

# * Commands that must NOT be swallowed by the warn conversation fallback.
_WARN_ESCAPE_CMDS = _UNWARN_CMDS | _WARNLIST_CMDS | _RESET_CMDS

__handlers__ = [
    warn_conversation(cmd_warn_entry, _WARN_CMDS, escape_filter=_WARN_ESCAPE_CMDS),
    MessageHandler(_UNWARN_CMDS, cmd_unwarn),
    MessageHandler(_WARNLIST_CMDS, cmd_warnlist),
    MessageHandler(_RESET_CMDS, cmd_resetwarns),
]
