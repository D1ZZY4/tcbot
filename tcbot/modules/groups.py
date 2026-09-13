# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""tcgroups command handler: lists all connected federation groups."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db

if TYPE_CHECKING:
    from telegram import Update
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.keyboards import tcgroups_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_edit, safe_reply
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CB_LIMIT: int = 15

# * Telegram caps message text at ~4096 chars; _render() truncates to this
# * budget so large federations get a partial list instead of an error.
_MAX_RENDER_CHARS: int = 3800

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Groups"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("groups.help.overview", locale, community=cfg.community_name)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("groups.help.commands.body", locale),
        ),
        replies.who_section(replies.context_anyone(locale), locale),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("groups.help.what.body", locale, community=cfg.community_name),
        ),
        (
            replies.sec_examples(locale),
            t("groups.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────── Helper Functions ──────────────────────── #


def _render(
    groups: list[GroupDoc], *, detailed: bool, locale: str | None = None
) -> str:
    """Render the group list, truncating to fit Telegram's message limit.

    Telegram rejects messages over ~4096 chars; an unbounded render raises
    BadRequest (swallowed by callers, leaving the user with nothing) on
    large federations. Cap the body and name the remainder instead.
    """
    header = t("groups.list.header", locale, n=len(groups))
    lines = [header]
    used = len(header) + 1
    for i, g in enumerate(groups):
        title = g.get("title", "Unknown")
        if detailed:
            line = t(
                "groups.list.item_detailed",
                locale,
                title=title,
                id=Safe(code(str(g.get("chat_id", 0)))),
            )
        else:
            line = t("groups.list.item", locale, title=title)
        if used + len(line) + 1 > _MAX_RENDER_CHARS:
            lines.append(
                t("groups.list.more", locale, n=len(groups) - i),
            )
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


# ────────── Command for see Connected Groups </tcgroups> ────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_tcfgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the list of all currently active connected groups (truncated to fit)."""
    locale = await locale_for_update(update)
    msg = update.effective_message
    if msg is None:
        return

    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during tcgroups")
        await safe_reply(
            msg,
            replies.err_groups_load_failed(locale, plain=True),
            log_label="tcgroups groups-failed",
            parse_mode=None,
        )
        return
    if not groups:
        await safe_reply(
            msg,
            t("groups.menu.empty", locale, community=cfg.community_name, plain=True),
            log_label="tcgroups no-groups",
            parse_mode=None,
        )
        return

    await safe_reply(
        msg,
        _render(groups, detailed=False, locale=locale),
        log_label="tcgroups list",
        reply_markup=tcgroups_kb(detailed=False, locale=locale),
    )


# ────────────── Callback Handlers (Details & Simple) ────────────── #


async def _toggle(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, *, detailed: bool
) -> None:
    q = update.callback_query
    if q is None or q.message is None:
        return
    locale = await locale_for_update(update)

    cbq_msg = q.message  # type: ignore[assignment]
    # * No per-user snapshot: active_groups() is already L1+L2 cached
    # * (30 s), so every toggle reads the shared cache instead of a
    # * per-user copy with its own divergent TTL.
    # * q.answer() and active_groups() are independent; run in parallel.
    _, groups_r = await asyncio.gather(
        q.answer(), db.groups_db.active_groups(), return_exceptions=True
    )
    if isinstance(groups_r, BaseException):
        # * Never render an empty list from a failed read: during an
        # * outage that would claim "Count: 0" for a healthy federation.
        # * Keep the toggle keyboard so re-tapping retries the fetch.
        log.warning("tcgroups toggle groups fetch failed: %s", groups_r)
        await safe_edit(
            cbq_msg,  # type: ignore[arg-type]
            replies.err_groups_load_failed(locale, plain=False),
            reply_markup=tcgroups_kb(detailed=detailed, locale=locale),
        )
        return
    groups = groups_r
    await safe_edit(
        cbq_msg,  # type: ignore[arg-type]
        _render(groups, detailed=detailed, locale=locale),
        reply_markup=tcgroups_kb(detailed=detailed, locale=locale),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_groups_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the groups listing to detailed view (shows full chat IDs)."""
    await _toggle(update, ctx, detailed=True)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the groups listing to simple view (condensed, no full chat IDs)."""
    await _toggle(update, ctx, detailed=False)


# ──────────────────────────── Handlers ──────────────────────────── #

_GROUPS_CMDS = build_prefixed_filters("tcgroups") | build_prefixed_filters("tcg")

__handlers__ = [
    MessageHandler(_GROUPS_CMDS, cmd_tcfgroups),
    CallbackQueryHandler(on_groups_details, pattern=r"^groups_details$"),
    CallbackQueryHandler(on_groups_simple, pattern=r"^groups_simple$"),
]
