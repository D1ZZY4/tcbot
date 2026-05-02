# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban list flow for /tcstats — numbered list, detail view, search."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import database as db
from tcbot.modules.helper.formatter import code, esc, mention

_PAGE_SIZE = 6
_SEARCH_KEY = "stats_bans_search"


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _bans_list_kb(page: int, total: int, n_items: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    rows: list[list] = []

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"stats_bans:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"stats_bans:{page + 1}"))
    if nav:
        rows.append(nav)

    num_btns = [
        InlineKeyboardButton(str(i + 1), callback_data=f"stats_ban_item:{page}:{i}")
        for i in range(n_items)
    ]
    for i in range(0, len(num_btns), 3):
        rows.append(num_btns[i: i + 3])

    rows.append([InlineKeyboardButton("Search", callback_data="stats_bans_search")])
    rows.append([InlineKeyboardButton("Back",   callback_data="stats_main")])
    return InlineKeyboardMarkup(rows)


def _detail_kb(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data=f"stats_bans:{page}")],
    ])


def _search_result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel", callback_data="stats_bans:0")],
    ])


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop(_SEARCH_KEY, None)

    page = int(q.data.split(":")[1])
    bans = await db.bans_db.active_bans()
    total = len(bans)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages - 1)
    chunk = bans[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>User Bans ({total})</b>\n"]
    for i, ban in enumerate(chunk, start=1):
        uid = ban["banned_user_id"]
        fname = await db.users_db.get_first_name(uid, str(uid))
        lines.append(f"{page * _PAGE_SIZE + i}. {esc(fname)} — {code(str(uid))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_bans_list_kb(page, total, len(chunk)),
    )


async def on_stats_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    _, page_str, idx_str = q.data.split(":")
    page = int(page_str)
    idx = int(idx_str)

    bans = await db.bans_db.active_bans()
    ban = bans[page * _PAGE_SIZE + idx]

    uid = ban["banned_user_id"]
    aid = ban["admin_user_id"]
    fname  = await db.users_db.get_first_name(uid, str(uid))
    aname  = await db.users_db.get_first_name(aid, str(aid))
    ts = ban["timestamp"].strftime("%Y-%m-%d %H:%M UTC") if ban.get("timestamp") else "Unknown"

    text = (
        f"<b>Ban Details</b>\n\n"
        f"User: {mention(uid, fname)} {code(str(uid))}\n"
        f"Ban ID: {code(ban['ban_id'])}\n"
        f"Reason: {esc(ban.get('reason', 'No reason'))}\n"
        f"Banned by: {mention(aid, aname)}\n"
        f"Date: {ts}"
    )
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_detail_kb(page))


async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("Send me a name or user ID to search", show_alert=True)
    ctx.user_data[_SEARCH_KEY] = True


async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get(_SEARCH_KEY):
        return
    ctx.user_data.pop(_SEARCH_KEY, None)

    query = update.effective_message.text.strip().lower()
    bans = await db.bans_db.active_bans()

    results = []
    for ban in bans:
        uid = ban["banned_user_id"]
        if query.isdigit() and str(uid) == query:
            results.append(ban)
        elif not query.isdigit():
            fname = await db.users_db.get_first_name(uid, "")
            if query in fname.lower():
                results.append(ban)

    if not results:
        await update.effective_message.reply_text(
            f"No banned user found matching <code>{esc(query)}</code>.",
            parse_mode="HTML",
            reply_markup=_search_result_kb(),
        )
        return

    lines = [f"<b>Search: \"{esc(query)}\" ({len(results)} found)</b>\n"]
    for i, ban in enumerate(results, 1):
        uid = ban["banned_user_id"]
        fname = await db.users_db.get_first_name(uid, str(uid))
        lines.append(f"{i}. {esc(fname)} — {code(str(uid))}")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_search_result_kb(),
    )


handlers = [
    CallbackQueryHandler(on_stats_bans,        pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(on_stats_ban_item,     pattern=r"^stats_ban_item:\d+:\d+$"),
    CallbackQueryHandler(on_stats_bans_search,  pattern=r"^stats_bans_search$"),
    MessageHandler(filters.TEXT & ~filters.COMMAND, on_bans_search_input),
]
