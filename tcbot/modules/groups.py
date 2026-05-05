# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Federation groups listing
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.modules.helper.formatter import code, esc
from tcbot.modules.helper.parse_editmsg import safe_edit
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Groups"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcfgroups</code> (alias: <code>/tcg</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Anyone, no special permissions needed.\n\n"

    "<b>Where to use it</b>\n"
    "Bot PM, exec group, or any connected group.\n\n"

    "<b>What it does</b>\n"
    f"Shows all groups currently connected to {cfg.community_name}. "
    "Default view shows group names only. "
    "Tap <b>Details</b> to also see each group's chat ID.\n\n"

    "<b>Example</b>\n"
    "<code>/tcfgroups</code> or <code>/tcg</code>"
)


def _render(groups: list[dict], detailed: bool) -> str:
    lines = [f"<b>Connected Groups</b>\n\nCount: {len(groups)}\n"]
    for g in groups:
        if detailed:
            lines.append(f"- {esc(g['title'])} — {code(str(g['chat_id']))}")
        else:
            lines.append(f"- {esc(g['title'])}")
    return "\n".join(lines)


def _kb(detailed: bool) -> InlineKeyboardMarkup:
    if detailed:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("Simple", callback_data="groups_simple"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Details", callback_data="groups_details"),
    ]])


async def cmd_tcfgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text(f"No groups are currently connected to {cfg.community_name}.")
        return
    ctx.user_data["groups_cache"] = groups
    await update.effective_message.reply_text(
        _render(groups, False), parse_mode="HTML", reply_markup=_kb(False)
    )


async def _toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, detailed: bool) -> None:
    q = update.callback_query
    await q.answer()
    groups = ctx.user_data.get("groups_cache")
    if not groups:
        groups = await db.groups_db.active_groups()
        ctx.user_data["groups_cache"] = groups
    await safe_edit(q.message, _render(groups, detailed), reply_markup=_kb(detailed))


async def on_groups_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, ctx, True)


async def on_groups_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, ctx, False)


_GROUPS_FILTER = (
    build_prefixed_filters("tcfgroups")
    | build_prefixed_filters("tcg")
)

__handlers__ = [
    MessageHandler(_GROUPS_FILTER, cmd_tcfgroups),
    CallbackQueryHandler(on_groups_details, pattern=r"^groups_details$"),
    CallbackQueryHandler(on_groups_simple,  pattern=r"^groups_simple$"),
]
