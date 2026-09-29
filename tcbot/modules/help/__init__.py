# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help command and callback handlers."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, MessageHandler

from tcbot.modules.help.builder import (
    _MODULE_NAME_MAP,
    _TOPICS_SORTED,
    HELP_CONTENT,
    HELP_TOPICS_CMD,
    HELP_TOPICS_MENU,
    _builder_help,
    _help_index_text,
    _module_map_for_locale,
    _module_text,
    _prefix_note,
    _section_buttons,
    _topics_for_locale,
)
from tcbot.modules.help.callbacks import (
    _render_help_index,
    _show_module,
    _show_section,
    on_help_menu,
    on_help_menu_group,
    on_help_section,
    on_help_topic_any,
    on_helpc_main,
)
from tcbot.modules.help.command import (
    _RL_CB_LIMIT,
    _RL_CMD_LIMIT,
    _RL_PERIOD_S,
    cmd_help,
)
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = None

__all__ = [
    "HELP_CONTENT",
    "HELP_TOPICS_CMD",
    "HELP_TOPICS_MENU",
    "_HELP_CMDS",
    "_MODULE_NAME_MAP",
    "_RL_CB_LIMIT",
    "_RL_CMD_LIMIT",
    "_RL_PERIOD_S",
    "_TOPICS_SORTED",
    "__handlers__",
    "__module_name__",
    "_builder_help",
    "_help_index_text",
    "_module_map_for_locale",
    "_module_text",
    "_prefix_note",
    "_render_help_index",
    "_section_buttons",
    "_show_module",
    "_show_section",
    "_topics_for_locale",
    "cmd_help",
    "on_help_menu",
    "on_help_menu_group",
    "on_help_section",
    "on_help_topic_any",
    "on_helpc_main",
]


# ──────────────────────────── Handlers ──────────────────────────── #

_HELP_CMDS = build_prefixed_filters("help")

__handlers__ = [
    MessageHandler(_HELP_CMDS, cmd_help),
    CallbackQueryHandler(on_help_menu, pattern=r"^help_menu$"),
    CallbackQueryHandler(on_help_menu_group, pattern=r"^help_menu_group$"),
    CallbackQueryHandler(on_helpc_main, pattern=r"^helpc_main$"),
    # * Section callbacks (helps_<mod>:<idx> for the menu path,
    # * helpcs_<mod>:<idx> for the command path) registered before the
    # * module-level catch-all so the more-specific pattern wins.
    CallbackQueryHandler(on_help_section, pattern=r"^(helps|helpcs)_\w+:\d+$"),
    CallbackQueryHandler(on_help_topic_any, pattern=r"^(help|helpc)_\w+$"),
]
