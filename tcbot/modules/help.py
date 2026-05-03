# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Help command – content is collected dynamically from each module's
__module_name__ and __help_text__ attributes."""

from __future__ import annotations

import importlib
import logging

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot.modules import ALL_MODULES
from tcbot.modules.helper import keyboards
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)


## ---------------------------------------------------------------------------
## Build help content dynamically from every loaded module
## ---------------------------------------------------------------------------


def _build_help_content() -> dict[str, tuple[str, str]]:
    """
    Iterate over ALL_MODULES and collect modules that expose both
    __module_name__ (not None) and __help_text__.
    Key format: "help_<mod_filename>"  e.g. "help_banning", "help_admins"
    """
    content: dict[str, tuple[str, str]] = {}
    for mod_name in ALL_MODULES:
        try:
            mod = importlib.import_module(f"tcbot.modules.{mod_name}")
            name = getattr(mod, "__module_name__", None)
            text = getattr(mod, "__help_text__", None)
            if name and text:
                content[f"help_{mod_name}"] = (name, text)
        except Exception as exc:
            log.warning("Could not read help from %s: %s", mod_name, exc)
    return content


HELP_CONTENT = _build_help_content()

## Pre-built list of (label, callback_data) for the keyboard
HELP_TOPICS: list[tuple[str, str]] = [
    (name, key) for key, (name, _) in HELP_CONTENT.items()
]


## ---------------------------------------------------------------------------
## Handlers
## ---------------------------------------------------------------------------


_HELP_INDEX_TEXT = (
    "<b>{bot_name} Help</b>\n"
    "This bot manages {community} groups, bans, appeals, and more. "
    "Select a topic below."
)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    bot_name = ctx.bot.first_name or "TC Bot"
    await update.effective_message.reply_text(
        _HELP_INDEX_TEXT.format(bot_name=bot_name, community=cfg.community_name),
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(HELP_TOPICS),
    )


async def on_menu_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    bot_name = ctx.bot.first_name or "TC Bot"
    await q.edit_message_text(
        _HELP_INDEX_TEXT.format(bot_name=bot_name, community=cfg.community_name),
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(HELP_TOPICS),
    )


async def on_help_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    topic = q.data
    if topic not in HELP_CONTENT:
        await q.edit_message_text("Topic not found.", reply_markup=keyboards.back_to_help_kb())
        return
    name, text = HELP_CONTENT[topic]
    await q.edit_message_text(
        f"<b>Help for {name}</b>\n\n{text}",
        parse_mode="HTML",
        reply_markup=keyboards.back_to_help_kb(),
    )


_HELP_FILTER = build_prefixed_filters("help") | build_prefixed_filters("commands")

__handlers__ = [
    MessageHandler(_HELP_FILTER, cmd_help),
    CallbackQueryHandler(on_menu_help, pattern=r"^menu_help$"),
    CallbackQueryHandler(on_help_topic, pattern=r"^help_\w+$"),
]
