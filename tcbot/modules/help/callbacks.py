# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help callback handlers: index, module overview, and section renders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot.modules.help.builder import (
    _builder_help,
    _help_index_text,
    _module_text,
    _section_buttons,
    _topics_for_locale,
)
from tcbot.modules.help.command import _RL_CB_LIMIT, _RL_PERIOD_S
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import answer_and_edit
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

log = get_logger(__name__)


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
