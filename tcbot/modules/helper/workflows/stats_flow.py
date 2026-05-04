# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban list flow for /tcstats — numbered list, detail view, full search flow."""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.formatter import code, esc
from tcbot.utils.prefixes import ANY_CMD_FILTER

_PAGE_SIZE    = 6
_SEARCH_KEY   = "stats_search_active"
_RESULTS_KEY  = "stats_search_results"
_MSG_KEY      = "stats_search_msg_id"
_CHAT_KEY     = "stats_search_chat_id"


## ---------------------------------------------------------------------------
## Keyboards
## ---------------------------------------------------------------------------

def _bans_list_kb(page: int, total: int, n_items: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    rows: list[list] = []

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"stats_bans:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"stats_bans:{page + 1}"))
    if nav:
        rows.append(nav)

    num_btns = [
        InlineKeyboardButton(str(i + 1), callback_data=f"stats_ban_item:{page}:{i}")
        for i in range(n_items)
    ]
    for i in range(0, len(num_btns), 3):
        rows.append(num_btns[i: i + 3])

    rows.append([InlineKeyboardButton("Search",  callback_data="stats_bans_search")])
    rows.append([InlineKeyboardButton("« Back", callback_data="stats_main")])
    return InlineKeyboardMarkup(rows)


def _search_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel", callback_data="stats_search_cancel")],
    ])


def _search_results_kb(n: int) -> InlineKeyboardMarkup:
    rows: list[list] = []
    num_btns = [
        InlineKeyboardButton(str(i + 1), callback_data=f"stats_search_item:{i}")
        for i in range(n)
    ]
    for i in range(0, len(num_btns), 3):
        rows.append(num_btns[i: i + 3])
    rows.append([InlineKeyboardButton("New Search", callback_data="stats_bans_search")])
    rows.append([InlineKeyboardButton("Cancel",     callback_data="stats_search_cancel")])
    return InlineKeyboardMarkup(rows)


def _search_detail_kb(proof_link: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if proof_link:
        rows.append([InlineKeyboardButton("View Proof", url=proof_link)])
    rows.append([InlineKeyboardButton("Back to Results", callback_data="stats_search_back")])
    return InlineKeyboardMarkup(rows)


def _ban_detail_kb(page: int, proof_link: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if proof_link:
        rows.append([InlineKeyboardButton("View Proof", url=proof_link)])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"stats_bans:{page}")])
    return InlineKeyboardMarkup(rows)


## ---------------------------------------------------------------------------
## Bans list handlers
## ---------------------------------------------------------------------------

async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q    = update.callback_query
    _clear_search(ctx)
    page = int(q.data.split(":")[1])

    _, bans = await asyncio.gather(q.answer(), db.bans_db.active_bans())
    total       = len(bans)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page        = min(page, total_pages - 1)
    chunk       = bans[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    uids   = [ban["banned_user_id"] for ban in chunk]
    fnames = await asyncio.gather(*[db.users_db.get_first_name(uid, str(uid)) for uid in uids])

    lines = [f"<b>User Bans ({total})</b>\n"]
    for i, (ban, fname) in enumerate(zip(chunk, fnames), start=1):
        uid = ban["banned_user_id"]
        lines.append(f"{page * _PAGE_SIZE + i}. {esc(fname)} — {code(str(uid))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_bans_list_kb(page, total, len(chunk)),
    )


async def on_stats_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q              = update.callback_query
    _, page_str, idx_str = q.data.split(":")
    page           = int(page_str)
    idx            = int(idx_str)

    _, bans = await asyncio.gather(q.answer(), db.bans_db.active_bans())
    ban              = bans[page * _PAGE_SIZE + idx]
    text, proof_link = await build_ban_detail(ban)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_ban_detail_kb(page, proof_link))


## ---------------------------------------------------------------------------
## Search flow handlers
## ---------------------------------------------------------------------------

def _clear_search(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_SEARCH_KEY, _RESULTS_KEY, _MSG_KEY, _CHAT_KEY):
        ctx.user_data.pop(key, None)


async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    ctx.user_data[_SEARCH_KEY] = True
    ctx.user_data[_MSG_KEY]    = q.message.message_id
    ctx.user_data[_CHAT_KEY]   = q.message.chat_id
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            "<b>Search User Bans</b>\n\nSend a name or user ID in the chat.",
            parse_mode="HTML",
            reply_markup=_search_panel_kb(),
        ),
    )


async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.user_data is None or not ctx.user_data.get(_SEARCH_KEY):
        return
    ctx.user_data.pop(_SEARCH_KEY, None)

    query = update.effective_message.text.strip()

    if query.isdigit():
        ## Targeted lookup — skip full scan for numeric queries
        ban     = await db.bans_db.get_active_ban(int(query))
        results = [ban] if ban else []
    else:
        bans   = await db.bans_db.active_bans()
        ## Fetch all names in parallel, then filter by query
        uids   = [ban["banned_user_id"] for ban in bans]
        fnames = await asyncio.gather(*[db.users_db.get_first_name(uid, "") for uid in uids])
        results = [
            ban for ban, fname in zip(bans, fnames)
            if query.lower() in fname.lower()
        ]

    ctx.user_data[_RESULTS_KEY] = results

    chat_id = ctx.user_data.get(_CHAT_KEY)
    msg_id  = ctx.user_data.get(_MSG_KEY)

    try:
        await update.effective_message.delete()
    except Exception:
        pass

    if not results:
        await ctx.bot.edit_message_text(
            f"<b>Search: \"{esc(query)}\"</b>\n\nNo results found.",
            chat_id=chat_id, message_id=msg_id,
            parse_mode="HTML",
            reply_markup=_search_results_kb(0),
        )
        return

    ## Fetch display names for results in parallel
    result_uids   = [ban["banned_user_id"] for ban in results]
    result_fnames = await asyncio.gather(
        *[db.users_db.get_first_name(uid, str(uid)) for uid in result_uids]
    )
    lines = [f"<b>Search: \"{esc(query)}\" ({len(results)} found)</b>\n"]
    for i, (ban, fname) in enumerate(zip(results, result_fnames), 1):
        uid = ban["banned_user_id"]
        lines.append(f"{i}. {esc(fname)} — {code(str(uid))}")

    await ctx.bot.edit_message_text(
        "\n".join(lines),
        chat_id=chat_id, message_id=msg_id,
        parse_mode="HTML",
        reply_markup=_search_results_kb(len(results)),
    )


async def on_stats_search_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q   = update.callback_query
    idx = int(q.data.split(":")[1])

    results = ctx.user_data.get(_RESULTS_KEY, [])
    if idx >= len(results):
        await q.answer("Result no longer available.", show_alert=True)
        return

    _, (text, proof_link) = await asyncio.gather(
        q.answer(),
        build_ban_detail(results[idx]),
    )
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_search_detail_kb(proof_link))


async def on_stats_search_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    results = ctx.user_data.get(_RESULTS_KEY, [])

    if not results:
        ctx.user_data[_SEARCH_KEY] = True
        await asyncio.gather(
            q.answer(),
            q.edit_message_text(
                "<b>Search User Bans</b>\n\nSend a name or user ID in the chat.",
                parse_mode="HTML",
                reply_markup=_search_panel_kb(),
            ),
        )
        return

    uids   = [ban["banned_user_id"] for ban in results]
    _, fnames = await asyncio.gather(
        q.answer(),
        asyncio.gather(*[db.users_db.get_first_name(uid, str(uid)) for uid in uids]),
    )

    lines = [f"<b>Search Results ({len(results)} found)</b>\n"]
    for i, (ban, fname) in enumerate(zip(results, fnames), 1):
        uid = ban["banned_user_id"]
        lines.append(f"{i}. {esc(fname)} — {code(str(uid))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_search_results_kb(len(results)),
    )


async def on_stats_search_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    _clear_search(ctx)

    _, bans = await asyncio.gather(q.answer(), db.bans_db.active_bans())
    total  = len(bans)
    chunk  = bans[:_PAGE_SIZE]

    uids   = [ban["banned_user_id"] for ban in chunk]
    fnames = await asyncio.gather(*[db.users_db.get_first_name(uid, str(uid)) for uid in uids])

    lines = [f"<b>User Bans ({total})</b>\n"]
    for i, (ban, fname) in enumerate(zip(chunk, fnames), start=1):
        uid = ban["banned_user_id"]
        lines.append(f"{i}. {esc(fname)} — {code(str(uid))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_bans_list_kb(0, total, len(chunk)),
    )


## ---------------------------------------------------------------------------

handlers = [
    CallbackQueryHandler(on_stats_bans,          pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(on_stats_ban_item,       pattern=r"^stats_ban_item:\d+:\d+$"),
    CallbackQueryHandler(on_stats_bans_search,    pattern=r"^stats_bans_search$"),
    CallbackQueryHandler(on_stats_search_item,    pattern=r"^stats_search_item:\d+$"),
    CallbackQueryHandler(on_stats_search_back,    pattern=r"^stats_search_back$"),
    CallbackQueryHandler(on_stats_search_cancel,  pattern=r"^stats_search_cancel$"),
    MessageHandler(filters.TEXT & ~ANY_CMD_FILTER, on_bans_search_input),
]
