# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Connected chats list flow for /tcstats — paginated list with per-group detail view
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import database as db
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.utils.timedate_format import fmt_dt

_PAGE_SIZE = 6


## ── Detail builder ───────────────────────────────────────────────────────────

async def build_chat_detail(grp: dict) -> str:
    """Return a formatted detail card for a connected group document."""
    chat_id   = grp["chat_id"]
    title     = grp.get("title", "Unknown")
    added_by  = grp.get("added_by", 0)
    added_dt  = grp.get("added_date")

    adder_fname = await db.users_db.get_first_name(added_by, str(added_by))
    date_str    = fmt_dt(added_dt) if added_dt else "Unknown"

    return (
        "<b>Group Details</b>\n\n"
        f"Name: <b>{esc(title)}</b>\n"
        f"Chat ID: {code(str(chat_id))}\n\n"
        f"Connected by: {mention(added_by, adder_fname)}\n"
        f"Date: {date_str}"
    )


## ── Keyboards ────────────────────────────────────────────────────────────────

def _chats_list_kb(page: int, total: int, n_items: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    rows: list[list] = []

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"stats_chats:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"stats_chats:{page + 1}"))
    if nav:
        rows.append(nav)

    num_btns = [
        InlineKeyboardButton(str(i + 1), callback_data=f"stats_chat_item:{page}:{i}")
        for i in range(n_items)
    ]
    for i in range(0, len(num_btns), 3):
        rows.append(num_btns[i: i + 3])

    rows.append([InlineKeyboardButton("« Back", callback_data="stats_main")])
    return InlineKeyboardMarkup(rows)


def _chat_detail_kb(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=f"stats_chats:{page}")],
    ])


## ── Handlers ─────────────────────────────────────────────────────────────────

async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q    = update.callback_query
    page = int(q.data.split(":")[1])

    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    total       = len(groups)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page        = min(page, total_pages - 1)
    chunk       = groups[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>Connected Chats ({total})</b>\n"]
    for i, grp in enumerate(chunk, start=1):
        lines.append(
            f"{page * _PAGE_SIZE + i}. {esc(grp['title'])} — {code(str(grp['chat_id']))}"
        )

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_chats_list_kb(page, total, len(chunk)),
    )


async def on_stats_chat_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q              = update.callback_query
    _, page_str, idx_str = q.data.split(":")
    page           = int(page_str)
    idx            = int(idx_str)

    _, groups = await asyncio.gather(q.answer(), db.groups_db.active_groups())
    grp  = groups[page * _PAGE_SIZE + idx]
    text = await build_chat_detail(grp)
    await q.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=_chat_detail_kb(page),
    )


handlers = [
    CallbackQueryHandler(on_stats_chats,     pattern=r"^stats_chats:\d+$"),
    CallbackQueryHandler(on_stats_chat_item, pattern=r"^stats_chat_item:\d+:\d+$"),
]
