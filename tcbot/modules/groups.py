# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""tcgroups command handler: lists all connected federation groups."""

from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators
from tcbot.modules.helper.formatter import code, esc
from tcbot.modules.helper.parse_editmsg import safe_edit
from tcbot.utils.prefixes import build_prefixed_filters

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Groups"
__help_text__ = (
    f"Lists every group currently connected to {cfg.community_name}, with optional "
    "details view."
)

__help_sections__: list[tuple[str, str]] = [
    (
        "Commands & Aliases",
        "<code>/tcgroups</code> (alias: <code>/tcg</code>)",
    ),
    (
        "Who can use",
        "Anyone, no special permissions needed.",
    ),
    (
        "Where to use",
        "Bot PM, exec group, or any connected group.",
    ),
    (
        "What it does",
        f"Lists all groups currently connected to {cfg.community_name}, along with the total "
        f"count.\n\n"
        f"The default view shows group names only. Tap <b>Details</b> to expand the list and "
        f"show each group's chat ID alongside its name. Tap <b>Simple</b> to collapse back.",
    ),
    (
        "Example",
        "<code>/tcgroups</code> or <code>/tcg</code>",
    ),
]


# ──────────────────────── Helper Functions ──────────────────────── #


def _render(groups: list[GroupDoc], detailed: bool) -> str:
    lines = [f"<b>Connected Groups</b>\n\nCount: {len(groups)}\n"]
    for g in groups:
        if detailed:
            lines.append(f"- {esc(g['title'])} - {code(str(g['chat_id']))}")
        else:
            lines.append(f"- {esc(g['title'])}")
    return "\n".join(lines)


def _kb(detailed: bool) -> InlineKeyboardMarkup:
    if detailed:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Simple", callback_data="groups_simple"),
                ]
            ]
        )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Details", callback_data="groups_details"),
            ]
        ]
    )


# ────────── Command for see Connected Groups </tcgroups> ────────── #


@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_tcfgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text(
            f"No groups are currently connected to {cfg.community_name}."
        )
        return
    ctx.user_data["groups_cache"] = groups
    await update.effective_message.reply_text(
        _render(groups, False), parse_mode="HTML", reply_markup=_kb(False)
    )


# ────────────── Callback Handlers (Details & Simple) ────────────── #


async def _toggle(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, detailed: bool
) -> None:
    q = update.callback_query
    groups = ctx.user_data.get("groups_cache")
    if groups:
        await q.answer()
    else:
        # * q.answer + cache-miss DB fetch run in parallel
        _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
        ctx.user_data["groups_cache"] = groups
    await safe_edit(q.message, _render(groups, detailed), reply_markup=_kb(detailed))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_groups_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, ctx, True)


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, ctx, False)


# ──────────────────────────── Handlers ──────────────────────────── #

_GROUPS_CMDS = build_prefixed_filters("tcgroups") | build_prefixed_filters("tcg")

__handlers__ = [
    MessageHandler(_GROUPS_CMDS, cmd_tcfgroups),
    CallbackQueryHandler(on_groups_details, pattern=r"^groups_details$"),
    CallbackQueryHandler(on_groups_simple, pattern=r"^groups_simple$"),
]
