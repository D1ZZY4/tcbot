# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help command handler: renders the help index or one module topic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot.modules.help.builder import (
    _builder_help,
    _help_index_text,
    _module_map_for_locale,
    _module_text,
    _section_buttons,
    _topics_for_locale,
)
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CB_LIMIT: int = 15


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
