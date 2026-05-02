# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation groups listing with pagination."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper.formatter import code, esc
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Groups"
__help_text__ = (
    "<code>/tcfgroups</code> – list all affiliated federation groups (anyone).\n"
    "Aliases: <code>/groups</code>, <code>/listtc</code>"
)

_PAGE_SIZE = 10


def _groups_page(groups: list[dict], page: int, add_back: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    total = len(groups)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    start = page * _PAGE_SIZE
    chunk = groups[start: start + _PAGE_SIZE]

    lines = [f"<b>Affiliated Groups ({total})</b>  Page {page + 1}/{total_pages}\n"]
    for grp in chunk:
        lines.append(f"- {esc(grp['title'])} {code(str(grp['chat_id']))}")

    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"groups_page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"groups_page:{page + 1}"))
    if nav:
        rows.append(nav)
    if add_back:
        rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    kb = InlineKeyboardMarkup(rows) if rows else None

    return "\n".join(lines), kb


async def cmd_tcfgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text("No groups are currently affiliated with TCF.")
        return

    text, kb = _groups_page(groups, 0)
    ctx.user_data["groups_list"] = groups
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def on_groups_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])
    groups = ctx.user_data.get("groups_list")
    if not groups:
        groups = await db.groups_db.active_groups()
        ctx.user_data["groups_list"] = groups
    text, kb = _groups_page(groups, page)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


## Spec aliases: /tcfgroups, /groups, /listtc
_GROUPS_FILTER = (
    build_prefixed_filters("tcfgroups")
    | build_prefixed_filters("groups")
    | build_prefixed_filters("listtc")
)

__handlers__ = [
    MessageHandler(_GROUPS_FILTER, cmd_tcfgroups),
    CallbackQueryHandler(on_groups_page, pattern=r"^groups_page:\d+$"),
]
