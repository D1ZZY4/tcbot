# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help command and callback handlers: renders module help index, module overview, and per-section topics."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot.modules import ALL_MODULES
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import answer_and_edit, safe_reply
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

log = logging.getLogger(__name__)

# * Help runtime prose lives in help.toml [error]/[note]/[module]/
# * [section]/[not_found]/[group].

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CB_LIMIT: int = 15

__module_name__ = None


# ────────────────────── Help Content Builder ────────────────────── #


def _builder_help(
    locale: str | None = None,
) -> dict[str, tuple[str, str, list[tuple[str, str]]]]:
    """Collect help content from every loaded module in the given locale.

    Returns a dict keyed by ``help_<module>`` mapping to
    ``(display_name, overview_text, sections)``. Modules without a
    ``get_help(locale)`` builder (non-help modules) are simply skipped.
    """
    content: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    for mod_name in ALL_MODULES:
        try:
            mod = importlib.import_module(f"tcbot.modules.{mod_name}")
            get_help = getattr(mod, "get_help", None)
            if not callable(get_help):
                continue
            try:
                h: object = get_help(locale)
            except Exception:
                h = None
            if isinstance(h, dict):
                content[f"help_{mod_name}"] = (
                    h["name"],
                    h["overview"],
                    list(h.get("sections", [])),
                )
        except Exception as exc:
            log.warning("Could not read help from %s: %s", mod_name, exc)
    return content


# ─────────────────────── Module-Level State ─────────────────────── #

HELP_CONTENT = _builder_help()

# * Sorted by display name (case-insensitive)
_TOPICS_SORTED: list[tuple[str, str]] = sorted(
    ((entry[0], key) for key, entry in HELP_CONTENT.items()),
    key=lambda t: t[0].lower(),
)

# * Menu-path topics; an explicit copy so a future mutation of one list
# * cannot silently reshape the other path's keyboard.
HELP_TOPICS_MENU: list[tuple[str, str]] = list(_TOPICS_SORTED)

# * Command-path topics; callback keys become "helpc_<mod>"
HELP_TOPICS_CMD: list[tuple[str, str]] = [
    (name, "helpc_" + key[5:]) for name, key in _TOPICS_SORTED
]

# * Module name → help key mapping for /help <module> lookup
# * (default-locale snapshot; per-request paths rebuild for the tapper's
# * locale via _module_map_for_locale below).
_MODULE_NAME_MAP: dict[str, str] = {}
for _key, _entry in HELP_CONTENT.items():
    _module_slug = _key[5:]
    _MODULE_NAME_MAP[_module_slug.lower()] = _key
    _MODULE_NAME_MAP[_entry[0].lower()] = _key


def _topics_for_locale(locale: str | None, *, menu: bool) -> list[tuple[str, str]]:
    """Build the help-index topic list in ``locale`` (names + callbacks).

    The module-level ``HELP_TOPICS_*`` lists are default-locale snapshots
    for import-time use; index renders call this so topic names follow the
    tapper's locale like every other keyboard.
    """
    content = _builder_help(locale)
    ordered = sorted(
        ((entry[0], key) for key, entry in content.items()),
        key=lambda item: item[0].lower(),
    )
    if menu:
        return list(ordered)
    return [(name, "helpc_" + key[5:]) for name, key in ordered]


def _module_map_for_locale(locale: str | None) -> dict[str, str]:
    """Build the module-name → help-key map in ``locale`` for /help <name>."""
    mapping: dict[str, str] = {}
    for key, entry in _builder_help(locale).items():
        slug = key[5:]
        mapping[slug.lower()] = key
        mapping[entry[0].lower()] = key
    return mapping


def _help_index_text(botname: str, locale: str | None = None) -> str:
    """Build the help index header for the given plain-text bot display name."""
    # * Title renders plain then bolds outside: the engine would double
    # * escape the name if it escaped first, and plain alone would leave
    # * a markup-bearing bot name unescaped. bold() escapes exactly once.
    return t(
        "help.index.body",
        locale,
        title=Safe(bold(t("help.index.title", locale, botname=botname, plain=True))),
        community=cfg.community_name,
    )


# ──────────────────────── Shared Renderers ──────────────────────── #


def _prefix_note(locale: str | None = None) -> str:
    """Render the command-prefix footer note in ``locale``.

    Prefixes come from frozen env config and never change at runtime, but
    the surrounding prose is translated, so this renders per request
    instead of once at import. The leading newline separates the note
    from the overview.
    """
    return "\n" + t(
        "help.note.prefixes",
        locale,
        prefixes=Safe(" ".join(code(p) for p in cfg.prefixes)),
    )


def _section_buttons(
    mod_slug: str,
    sections: list[tuple[str, str]],
    *,
    is_menu_path: bool,
) -> list[tuple[str, str]]:
    """Build (label, callback_data) pairs for each section."""
    prefix = "helps_" if is_menu_path else "helpcs_"
    return [
        (label, f"{prefix}{mod_slug}:{idx}") for idx, (label, _) in enumerate(sections)
    ]


def _module_text(name: str, overview: str, locale: str | None = None) -> str:
    """Compose the module-overview MarkdownV2 body."""
    return t(
        "help.module.body",
        locale,
        title=Safe(bold(t("help.module.title", locale, name=name, plain=True))),
        overview=Safe(overview),
        note=Safe(_prefix_note(locale)),
    )


async def _render_help_index(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    with_back_to_start: bool,
) -> None:
    """Edit the help index message on the appropriate callback query."""
    q = update.callback_query
    if q is None:
        return

    botname = ctx.bot.first_name or ""
    locale = await locale_for_update(update)
    kb = (
        keyboards.help_topics_menu_kb(_topics_for_locale(locale, menu=True), locale)
        if with_back_to_start
        else keyboards.help_topics_kb(_topics_for_locale(locale, menu=False))
    )
    await answer_and_edit(q, _help_index_text(botname, locale), reply_markup=kb)


async def _show_module(
    q: CallbackQuery,
    update: Update,
    menu_key: str,
    *,
    is_menu_path: bool,
) -> None:
    """Render a module overview with sub-section buttons + back to help index."""
    locale = await locale_for_update(update)
    content = _builder_help(locale)
    if menu_key not in content:
        back_kb = (
            keyboards.back_to_help_kb(locale)
            if is_menu_path
            else keyboards.back_to_help_cmd_kb(locale)
        )
        await answer_and_edit(
            q,
            t("help.error.topic_not_found", locale, plain=False),
            reply_markup=back_kb,
        )
        return

    name, overview, sections = content[menu_key]
    mod_slug = menu_key[5:]  # strip "help_"

    back_cb = "help_menu" if is_menu_path else "helpc_main"
    if sections:
        section_btns = _section_buttons(mod_slug, sections, is_menu_path=is_menu_path)
        kb = keyboards.module_help_kb(
            section_btns, back_callback=back_cb, locale=locale
        )
    else:
        kb = (
            keyboards.back_to_help_kb(locale)
            if is_menu_path
            else keyboards.back_to_help_cmd_kb(locale)
        )

    await answer_and_edit(q, _module_text(name, overview, locale), reply_markup=kb)


async def _show_section(
    q: CallbackQuery,
    update: Update,
    mod_slug: str,
    idx: int,
    *,
    is_menu_path: bool,
) -> None:
    """Render a single help section + back-to-module button."""
    locale = await locale_for_update(update)
    content = _builder_help(locale)
    menu_key = f"help_{mod_slug}"
    back_module_cb = ("help_" if is_menu_path else "helpc_") + mod_slug

    if menu_key not in content:
        await answer_and_edit(
            q,
            t("help.error.topic_not_found", locale, plain=False),
            reply_markup=keyboards.back_to_module_kb(back_module_cb, locale),
        )
        return

    name, _, sections = content[menu_key]
    if idx < 0 or idx >= len(sections):
        await answer_and_edit(
            q,
            t("help.error.section_not_found", locale, plain=False),
            reply_markup=keyboards.back_to_module_kb(back_module_cb, locale),
        )
        return

    label, section_content = sections[idx]
    body = t(
        "help.section.body",
        locale,
        title=Safe(bold(f"{name} > {label}")),
        content=Safe(section_content),
    )
    await answer_and_edit(
        q, body, reply_markup=keyboards.back_to_module_kb(back_module_cb, locale)
    )


# ──────────────────────── Command Handlers ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the help index, or a specific topic when an argument is given."""
    msg = update.effective_message
    if msg is None:
        return

    botname = ctx.bot.first_name or ""
    args = parse_cmd_args(msg.text)
    locale = await locale_for_update(update)
    content = _builder_help(locale)
    name_map = _module_map_for_locale(locale)

    if args:
        query = " ".join(args).strip().lower()
        help_key = name_map.get(query)

        if help_key and help_key in content:
            name, overview, sections = content[help_key]
            mod_slug = help_key[5:]
            if sections:
                section_btns = _section_buttons(mod_slug, sections, is_menu_path=False)
                kb = keyboards.module_help_kb(
                    section_btns, back_callback="helpc_main", locale=locale
                )
            else:
                kb = keyboards.back_to_help_cmd_kb(locale)
            await safe_reply(
                msg,
                _module_text(name, overview, locale),
                log_label="cmd_help module",
                reply_markup=kb,
            )
            return

        candidates = sorted(
            name_map,
            key=lambda k: (query not in k, abs(len(k) - len(query))),
        )[:3]
        suggestion = ", ".join(code(f"/help {c}") for c in candidates if c)
        hint = (
            Safe(
                t(
                    "help.not_found.hint",
                    locale,
                    suggestions=Safe(suggestion),
                )
            )
            if suggestion
            else Safe("")
        )
        await safe_reply(
            msg,
            t(
                "help.not_found.body",
                locale,
                query=Safe(bold(query)),
                hint=hint,
            ),
            log_label="cmd_help not-found",
            reply_markup=keyboards.help_topics_kb(
                _topics_for_locale(locale, menu=False)
            ),
        )
        return

    await safe_reply(
        msg,
        _help_index_text(botname, locale),
        log_label="cmd_help index",
        reply_markup=keyboards.help_topics_kb(_topics_for_locale(locale, menu=False)),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_help_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level help index from the start-menu help button (includes back-to-start)."""
    await _render_help_index(update, ctx, with_back_to_start=True)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_help_menu_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Help tapped from group /start inline; answer with alert, no edit."""
    q = update.callback_query
    if q is None:
        return

    await q.answer(
        t("help.group.alert", await locale_for_update(update), plain=True),
        show_alert=True,
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_helpc_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level help index from a /helpc command callback (no back-to-start button)."""
    await _render_help_index(update, ctx, with_back_to_start=False)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_help_topic_any(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle help_<mod> and helpc_<mod> module overview callbacks."""
    q = update.callback_query
    if q is None or not q.data:
        return

    data = q.data
    if data.startswith("helpc_"):
        await _show_module(
            q, update, "help_" + data[len("helpc_") :], is_menu_path=False
        )
    else:
        await _show_module(q, update, data, is_menu_path=True)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_help_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle helps_<mod>:<idx> and helpcs_<mod>:<idx> section callbacks."""
    q = update.callback_query
    if q is None or not q.data:
        return

    data = q.data
    is_menu_path = data.startswith("helps_")
    body = data[len("helps_") :] if is_menu_path else data[len("helpcs_") :]
    try:
        mod_slug, idx_str = body.split(":", 1)
        idx = int(idx_str)
    except ValueError:
        # * split(":", 1) unpacking raises ValueError (never IndexError).
        await q.answer(
            t(
                "help.error.invalid_section",
                await locale_for_update(update),
                plain=True,
            ),
            show_alert=True,
        )
        return
    await _show_section(q, update, mod_slug, idx, is_menu_path=is_menu_path)


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
