# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Help command – content is collected dynamically from each module's __module_name__ and __help_text__ attributes

from __future__ import annotations

import asyncio
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

## Sorted automatically by display name
_TOPICS_SORTED: list[tuple[str, str]] = sorted(
    ((name, key) for key, (name, _) in HELP_CONTENT.items()),
    key=lambda t: t[0].lower(),
)

## Menu-path topics — callback keys stay as "help_<mod>"
HELP_TOPICS_MENU: list[tuple[str, str]] = _TOPICS_SORTED

## Command-path topics — callback keys become "helpc_<mod>"
HELP_TOPICS_CMD: list[tuple[str, str]] = [
    (name, "helpc_" + key[5:]) for name, key in _TOPICS_SORTED
]


## ---------------------------------------------------------------------------
## Shared text
## ---------------------------------------------------------------------------


_HELP_INDEX_TEXT = (
    "<b>{bot_name} Help</b>\n"
    "This bot manages {community} groups, bans, appeals, and more. "
    "Select a topic below."
)


## ---------------------------------------------------------------------------
## Shared rendering helper
## ---------------------------------------------------------------------------


async def _render_help_index(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    with_back_to_start: bool,
) -> None:
    """Edit (or send) the help index message on the appropriate callback query."""
    q: CallbackQuery = update.callback_query
    bot_name = ctx.bot.first_name or "TC Bot"
    kb = keyboards.help_topics_menu_kb(HELP_TOPICS_MENU) if with_back_to_start else keyboards.help_topics_kb(HELP_TOPICS_CMD)
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _HELP_INDEX_TEXT.format(bot_name=bot_name, community=cfg.community_name),
            parse_mode="HTML",
            reply_markup=kb,
        ),
    )


## ---------------------------------------------------------------------------
## /help command handler  (PM or group — no back-to-start)
## ---------------------------------------------------------------------------


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    bot_name = ctx.bot.first_name or "TC Bot"
    await update.effective_message.reply_text(
        _HELP_INDEX_TEXT.format(bot_name=bot_name, community=cfg.community_name),
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(HELP_TOPICS_CMD),
    )


## ---------------------------------------------------------------------------
## Callback: Help button from start menu  (PM only — has back-to-start)
## ---------------------------------------------------------------------------


async def on_menu_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_help_index(update, ctx, with_back_to_start=True)


## ---------------------------------------------------------------------------
## Callback: Help button pressed inside a group (/start group inline button)
## ---------------------------------------------------------------------------


async def on_menu_help_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Help tapped from group /start inline — answer with alert, no edit."""
    q: CallbackQuery = update.callback_query
    await q.answer(
        "Use /help in this group to browse all commands.",
        show_alert=True,
    )


## ---------------------------------------------------------------------------
## Callback: "helpcmd_idx" — back to help index (command path, no back-to-start)
## ---------------------------------------------------------------------------


async def on_helpcmd_idx(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_help_index(update, ctx, with_back_to_start=False)


## ---------------------------------------------------------------------------
## Callback: topic selected from menu path  ("help_<mod>")
## ---------------------------------------------------------------------------


async def on_help_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    topic = q.data
    if topic not in HELP_CONTENT:
        await asyncio.gather(
            q.answer(),
            q.edit_message_text("Topic not found.", reply_markup=keyboards.back_to_help_kb()),
        )
        return
    name, text = HELP_CONTENT[topic]
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            f"<b>Help for {name}</b>\n\n{text}",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_help_kb(),
        ),
    )


## ---------------------------------------------------------------------------
## Callback: topic selected from command path  ("helpc_<mod>")
## ---------------------------------------------------------------------------


async def on_help_topic_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    ## "helpc_banning" → "help_banning"
    menu_key = "help_" + q.data[6:]
    if menu_key not in HELP_CONTENT:
        await asyncio.gather(
            q.answer(),
            q.edit_message_text("Topic not found.", reply_markup=keyboards.back_to_help_cmd_kb()),
        )
        return
    name, text = HELP_CONTENT[menu_key]
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            f"<b>Help for {name}</b>\n\n{text}",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_help_cmd_kb(),
        ),
    )


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------


_HELP_FILTER = build_prefixed_filters("help") | build_prefixed_filters("commands")

__handlers__ = [
    MessageHandler(_HELP_FILTER, cmd_help),
    CallbackQueryHandler(on_menu_help,        pattern=r"^menu_help$"),
    CallbackQueryHandler(on_menu_help_group,  pattern=r"^menu_help_group$"),
    CallbackQueryHandler(on_helpcmd_idx,      pattern=r"^helpcmd_idx$"),
    CallbackQueryHandler(on_help_topic,       pattern=r"^help_\w+$"),
    CallbackQueryHandler(on_help_topic_cmd,   pattern=r"^helpc_\w+$"),
]
