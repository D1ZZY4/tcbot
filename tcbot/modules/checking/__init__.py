# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""checkme and check handlers: self ban status and comprehensive user-profile view."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, MessageHandler

from tcbot.modules.checking.checkme import (
    _RL_CHECKME_CB_LIMIT,
    _RL_CMD_LIMIT,
    _RL_PERIOD_S,
    _ban_summary,
    cmd_checkme,
    on_checkme_back,
    on_checkme_detail,
)
from tcbot.modules.checking.views import (
    _RL_CHECK_CB_LIMIT,
    cmd_check,
    on_check_appeals,
    on_check_ban_item,
    on_check_bans,
    on_check_kicks,
    on_check_main,
    on_check_mutes,
    on_check_warn_chat,
    on_check_warns,
)
from tcbot.modules.helper import replies
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import build_prefixed_filters

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Check"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("checking.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("checking.help.commands.body", locale),
        ),
        replies.who_section(replies.context_anyone(locale), locale),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            "/checkme",
            t("checking.help.checkme.body", locale),
        ),
        (
            "/check",
            t("checking.help.check.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("checking.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────────── Handlers ──────────────────────────── #

_CHECKME_CMDS = build_prefixed_filters("checkme") | build_prefixed_filters("cme")
_CHECK_CMDS = build_prefixed_filters("check") | build_prefixed_filters("c")

__handlers__ = [
    MessageHandler(_CHECKME_CMDS, cmd_checkme),
    MessageHandler(_CHECK_CMDS, cmd_check),
    CallbackQueryHandler(on_checkme_detail, pattern=r"^checkme_detail:"),
    CallbackQueryHandler(on_checkme_back, pattern=r"^checkme_back:"),
    CallbackQueryHandler(on_check_main, pattern=r"^check_main:\d+$"),
    CallbackQueryHandler(on_check_bans, pattern=r"^check_bans:\d+:\d+$"),
    CallbackQueryHandler(on_check_ban_item, pattern=r"^check_ban_item:\d+:[a-z0-9]+$"),
    CallbackQueryHandler(on_check_warns, pattern=r"^check_warns:\d+$"),
    CallbackQueryHandler(
        on_check_warn_chat, pattern=r"^check_warn_chat:\d+:-?\d+:\d+$"
    ),
    CallbackQueryHandler(on_check_kicks, pattern=r"^check_kicks:\d+:\d+$"),
    CallbackQueryHandler(on_check_mutes, pattern=r"^check_mutes:\d+:\d+$"),
    CallbackQueryHandler(on_check_appeals, pattern=r"^check_appeals:\d+:\d+$"),
]

__all__ = [
    "_CHECKME_CMDS",
    "_CHECK_CMDS",
    "_RL_CHECKME_CB_LIMIT",
    "_RL_CHECK_CB_LIMIT",
    "_RL_CMD_LIMIT",
    "_RL_PERIOD_S",
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "_ban_summary",
    "cmd_check",
    "cmd_checkme",
    "get_help",
    "on_check_appeals",
    "on_check_ban_item",
    "on_check_bans",
    "on_check_kicks",
    "on_check_main",
    "on_check_mutes",
    "on_check_warn_chat",
    "on_check_warns",
    "on_checkme_back",
    "on_checkme_detail",
]
