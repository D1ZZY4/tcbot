# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""``/tcstats`` command and callback handlers: federation-wide overview and drill-downs."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, MessageHandler, filters

from tcbot.modules.helper import replies
from tcbot.modules.stats.command import (
    _parse_item_callback,
    _require_founder_list,
    cmd_stats,
)
from tcbot.modules.stats.search import (
    on_bans_search_input,
    on_stats_bans_search,
    on_stats_search_back,
    on_stats_search_cancel,
    on_stats_search_item,
)
from tcbot.modules.stats.views import (
    on_stats_admins,
    on_stats_ban_item,
    on_stats_bans,
    on_stats_chat_item,
    on_stats_chats,
    on_stats_main,
    on_stats_user_item,
    on_stats_users,
)
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

__module_name__ = "Stats"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("stats.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("stats.help.commands.body", locale),
        ),
        replies.who_section(replies.context_anyone(locale), locale),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("stats.help.what.body", locale),
        ),
        (
            t("stats.help.drills.title", locale, plain=True),
            t("stats.help.drills.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("stats.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]

_STATS_CMDS = build_prefixed_filters("tcstats") | build_prefixed_filters("tcs")

__handlers__ = [
    MessageHandler(_STATS_CMDS, cmd_stats),
    CallbackQueryHandler(on_stats_main, pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins$"),
    CallbackQueryHandler(on_stats_users, pattern=r"^stats_users:\d+$"),
    CallbackQueryHandler(
        on_stats_user_item, pattern=r"^stats_user_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_chats, pattern=r"^stats_chats:\d+$"),
    CallbackQueryHandler(
        on_stats_chat_item, pattern=r"^stats_chat_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_bans, pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(
        on_stats_ban_item, pattern=r"^stats_ban_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_bans_search, pattern=r"^stats_bans_search$"),
    CallbackQueryHandler(
        on_stats_search_item, pattern=r"^stats_search_item:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_search_back, pattern=r"^stats_search_back$"),
    CallbackQueryHandler(on_stats_search_cancel, pattern=r"^stats_search_cancel$"),
    # * Search input only matters in PM where the bans panel was opened;
    # * avoids absorbing every non-command text in groups.
    MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
        on_bans_search_input,
    ),
]

__all__ = [
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "_parse_item_callback",
    "_require_founder_list",
    "cmd_stats",
    "get_help",
    "on_bans_search_input",
    "on_stats_admins",
    "on_stats_ban_item",
    "on_stats_bans",
    "on_stats_bans_search",
    "on_stats_chat_item",
    "on_stats_chats",
    "on_stats_main",
    "on_stats_search_back",
    "on_stats_search_cancel",
    "on_stats_search_item",
    "on_stats_user_item",
    "on_stats_users",
]
