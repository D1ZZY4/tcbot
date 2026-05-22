# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Help command – index page and per-module topic viewer with menu and command paths."""

from __future__ import annotations

import asyncio
import importlib
import logging

from telegram import CallbackQuery, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot.modules import ALL_MODULES
from tcbot.modules.helper import decorators, keyboards
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

__module_name__ = None


## ── Build help content ─────────────────────────────────────────────────────

def _build_help_content() -> dict[str, tuple[str, str]]:
    """Collect modules that expose ``__module_name__`` and ``__help_text__``.

    Returns:
        Mapping of ``"help_<mod_filename>"`` → ``(display_name, help_text)``.
    """
    content: dict[str, tuple[str, str]] = {}
    for mod_name in ALL_MODULES:
        try:
            mod  = importlib.import_module(f"tcbot.modules.{mod_name}")
            name = getattr(mod, "__module_name__", None)
            text = getattr(mod, "__help_text__", None)
            if name and text:
                content[f"help_{mod_name}"] = (name, text)
        except Exception as exc:
            log.warning("Could not read help from %s: %s", mod_name, exc)
    return content


HELP_CONTENT = _build_help_content()

## Sorted by display name (case-insensitive)
_TOPICS_SORTED: list[tuple[str, str]] = sorted(
    ((name, key) for key, (name, _) in HELP_CONTENT.items()),
    key=lambda t: t[0].lower(),
)

## Menu-path topics - callback keys stay as "help_<mod>"
HELP_TOPICS_MENU: list[tuple[str, str]] = _TOPICS_SORTED

## Command-path topics - callback keys become "helpc_<mod>"
HELP_TOPICS_CMD: list[tuple[str, str]] = [
    (name, "helpc_" + key[5:]) for name, key in _TOPICS_SORTED
]

## Module name → help key mapping for /help <module> lookup
_MODULE_NAME_MAP: dict[str, str] = {}
for _key, (_dname, _) in HELP_CONTENT.items():
    ## "help_banning" → key "banning"; display name "Ban" → normalized "ban"
    _module_slug = _key[5:]                     ## "banning"
    _MODULE_NAME_MAP[_module_slug.lower()] = _key
    _MODULE_NAME_MAP[_dname.lower()]       = _key


## ── Prefix note ────────────────────────────────────────────────────────────

def _prefix_note() -> str:
    """Return an HTML footer listing every configured command prefix."""
    codes = " ".join(f"<code>{p}</code>" for p in cfg.prefixes)
    return f"\n<b>INFO!! Prefixes:</b> All commands also work with {codes}"


## ── Shared text ────────────────────────────────────────────────────────────

_HELP_INDEX_TEXT = (
    "<b>{botname} Help</b>\n\n"
    f"I manages groups connected on {cfg.community_name}. "
    "Select a topic below, or use <code>/help &lt;module&gt;</code> for direct access."
)


## ── Shared rendering helper ────────────────────────────────────────────────

async def _render_help_index(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    with_back_to_start: bool,
) -> None:
    """Edit the help index message on the appropriate callback query."""
    q: CallbackQuery = update.callback_query
    botname = ctx.bot.first_name
    kb = (
        keyboards.help_topics_menu_kb(HELP_TOPICS_MENU)
        if with_back_to_start
        else keyboards.help_topics_kb(HELP_TOPICS_CMD)
    )
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _HELP_INDEX_TEXT.format(botname=botname),
            parse_mode="HTML",
            reply_markup=kb,
        ),
    )


## ── /help command ──────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the help index, or a specific module's help if an arg is given.

    Usage::

        /help            → shows help topic index
        /help ban        → shows Ban module help directly
        /help banning    → same (module filename also accepted)
        /help admins     → shows Admins module help
    """
    botname = ctx.bot.first_name
    args    = parse_cmd_args(update.effective_message.text)

    if args:
        ## Attempt to resolve argument to a module
        query   = " ".join(args).strip().lower()
        help_key = _MODULE_NAME_MAP.get(query)

        if help_key and help_key in HELP_CONTENT:
            name, text = HELP_CONTENT[help_key]
            await update.effective_message.reply_text(
                f"<b>Help for {name}</b>\n\n{text}\n{_prefix_note()}",
                parse_mode="HTML",
                reply_markup=keyboards.back_to_help_cmd_kb(),
            )
            return

        ## Module not found - show closest matches from known names
        candidates = sorted(
            _MODULE_NAME_MAP,
            key=lambda k: (query not in k, abs(len(k) - len(query))),
        )[:3]
        suggestion = ", ".join(f"<code>/help {c}</code>" for c in candidates if c)
        hint = f"\n\nDid you mean: {suggestion}?" if suggestion else ""
        await update.effective_message.reply_text(
            f"Module <b>{query}</b> not found.{hint}",
            parse_mode="HTML",
            reply_markup=keyboards.help_topics_kb(HELP_TOPICS_CMD),
        )
        return

    ## No args - show full index
    await update.effective_message.reply_text(
        _HELP_INDEX_TEXT.format(botname=botname),
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(HELP_TOPICS_CMD),
    )


## ── Help from menu ─────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_help_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_help_index(update, ctx, with_back_to_start=True)


## ── Help in group ──────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_help_menu_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Help tapped from group /start inline - answer with alert, no edit."""
    q: CallbackQuery = update.callback_query
    await q.answer(
        "Use /help in this group to browse all commands.",
        show_alert=True,
    )


## ── Help index callback ────────────────────────────────────────────────────

@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_helpc_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_help_index(update, ctx, with_back_to_start=False)


## ── Shared topic renderer ──────────────────────────────────────────────────

async def _show_topic(q: CallbackQuery, menu_key: str, back_kb) -> None:
    """Render a help topic and edit the current message in place."""
    if menu_key not in HELP_CONTENT:
        await asyncio.gather(
            q.answer(),
            q.edit_message_text("Topic not found.", reply_markup=back_kb),
        )
        return
    name, text = HELP_CONTENT[menu_key]
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            f"<b>Help for {name}</b>\n\n{text}\n{_prefix_note()}",
            parse_mode="HTML",
            reply_markup=back_kb,
        ),
    )


## ── Help topic - unified handler (menu path + command path) ────────────────

@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_help_topic_any(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle both ``help_<mod>`` (menu path) and ``helpc_<mod>`` (command path).

    The two paths differ only in which back-button keyboard is used.
    ``helpc_*`` data is normalised to its ``help_*`` key before lookup.
    """
    q: CallbackQuery = update.callback_query
    if q.data.startswith("helpc_"):
        ## "helpc_banning" → "help_banning"
        await _show_topic(q, "help_" + q.data[6:], keyboards.back_to_help_cmd_kb())
    else:
        await _show_topic(q, q.data, keyboards.back_to_help_kb())


## ── Handlers ───────────────────────────────────────────────────────────────

_HELP_FILTER = build_prefixed_filters("help") | build_prefixed_filters("commands")

__handlers__ = [
    MessageHandler(_HELP_FILTER, cmd_help),
    CallbackQueryHandler(on_help_menu,       pattern=r"^help_menu$"),
    CallbackQueryHandler(on_help_menu_group, pattern=r"^help_menu_group$"),
    CallbackQueryHandler(on_helpc_main,      pattern=r"^helpc_main$"),
    ## Unified topic handler - catches both help_<mod> and helpc_<mod>
    ## Registered after specific patterns above so they take priority
    CallbackQueryHandler(on_help_topic_any,  pattern=r"^(help|helpc)_\w+$"),
]
