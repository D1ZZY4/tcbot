# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""``/tcstats`` command and callback handlers: federation-wide overview and drill-downs."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.parse_editmsg import safe_edit_cb
from tcbot.modules.helper.workflows.stats_flow import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    Stats,
)
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Stats"
__help_text__ = (
    "Live federation overview: Founder, staff, users, active bans, and "
    "connected groups, with drill-down menus for every section."
)

__help_sections__: list[tuple[str, str]] = [
    (
        "Commands & Aliases",
        "<code>/tcstats</code> (alias: <code>/tcs</code>)",
    ),
    (
        "Who can use",
        replies.CONTEXT_ANYONE,
    ),
    (
        "Where to use",
        replies.CONTEXT_BOT_OR_GROUP,
    ),
    (
        "What it does",
        "Shows a live federation summary: Founder, total staff broken down by "
        "role, the number of cached users, active federation bans, and "
        "connected chats.",
    ),
    (
        "Drill-downs",
        "<b>Staff Roster</b>: Founder, Admins, Developers, Testers, all listed "
        "with mentions.\n"
        "<b>Users</b>: paginated list of every cached user. Numbered buttons "
        "open a per-user detail card.\n"
        "<b>Connected Chats</b>: paginated list of every active group; "
        "drill-in shows owner, ID, and connect date.\n"
        "<b>User Bans</b>: paginated list of every active ban with a "
        "<b>Search</b> shortcut to look up a user by name or ID.\n\n"
        "Every view ends with a <b>« Back</b> button to the main summary.",
    ),
    (
        "Examples",
        "<code>/tcstats</code>\n<code>/tcs</code>",
    ),
]


# ──────────────────────── Command Handlers ──────────────────────── #


@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the federation overview message."""
    text, kb = await Stats.main()
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ──────────────────────── Callback Helpers ──────────────────────── #


async def _ack_and_render(q, data_coro) -> None:
    """Acknowledge the callback in parallel with the data coroutine, then edit.

    ``data_coro`` must be a coroutine that returns ``(text, kb)``.  Running
    ``q.answer()`` concurrently with the DB-heavy data fetch removes one
    sequential await per callback handler, matching the pattern used in
    checking.py.
    """
    _, (text, kb) = await asyncio.gather(q.answer(), data_coro)
    await safe_edit_cb(q, text, reply_markup=kb)


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level stats menu."""
    q = update.callback_query
    # * q.answer() and Stats.main() are independent; run in parallel.
    await _ack_and_render(q, Stats.main())


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the current staff roster page."""
    q = update.callback_query
    await _ack_and_render(q, Stats.staff_roster())


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of cached users."""
    q = update.callback_query
    page = int(q.data.split(":")[1])
    await _ack_and_render(q, Stats.users_list(page))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_user_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single cached user entry."""
    q = update.callback_query
    _, page_str, idx_str = q.data.split(":")
    await _ack_and_render(q, Stats.user_detail(int(page_str), int(idx_str)))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of connected groups."""
    q = update.callback_query
    page = int(q.data.split(":")[1])
    await _ack_and_render(q, Stats.chats_list(page))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_chat_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single connected group entry."""
    q = update.callback_query
    _, page_str, idx_str = q.data.split(":")
    await _ack_and_render(q, Stats.chat_detail(int(page_str), int(idx_str)))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated ban-list page and clear any active search state."""
    q = update.callback_query
    page = int(q.data.split(":")[1])
    Stats.clear_search(ctx)
    await _ack_and_render(q, Stats.bans_list(page))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single ban entry from the stats list."""
    q = update.callback_query
    _, page_str, idx_str = q.data.split(":")
    await _ack_and_render(q, Stats.ban_detail(int(page_str), int(idx_str)))


# ── Search panel ─────────────────────────────────────────────────────


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the user search prompt within the stats ban view."""
    q = update.callback_query
    # * Stats.open_search is synchronous; gather q.answer() with the edit directly.
    text, kb = Stats.open_search(ctx, q)
    await asyncio.gather(q.answer(), safe_edit_cb(q, text, reply_markup=kb))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text query message handler; only reacts when the search panel is active."""
    if ctx.user_data is None or not ctx.user_data.get(SEARCH_KEY):
        return
    ctx.user_data.pop(SEARCH_KEY, None)

    msg = update.effective_message
    query = (msg.text or "").strip()

    # * Run the search and delete the user's input message in parallel.
    results, _ = await asyncio.gather(
        Stats.search_run(query),
        msg.delete(),
        return_exceptions=True,
    )
    if isinstance(results, BaseException):
        results = []

    ctx.user_data[RESULTS_KEY] = results

    chat_id = ctx.user_data.get(CHAT_KEY)
    msg_id = ctx.user_data.get(MSG_KEY)
    text, kb = await Stats.search_results(query, results)
    if chat_id is not None and msg_id is not None:
        await ctx.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=msg_id,
            parse_mode="HTML",
            reply_markup=kb,
        )


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_search_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a search result selected by the user."""
    q = update.callback_query
    idx = int(q.data.split(":")[1])
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    await _ack_and_render(q, Stats.search_detail(results, idx))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_search_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to search results (or the open-search prompt) without re-running the query."""
    q = update.callback_query
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    if not results:
        # * open_search is synchronous; gather q.answer() with the edit directly.
        text, kb = Stats.open_search(ctx, q)
        await asyncio.gather(q.answer(), safe_edit_cb(q, text, reply_markup=kb))
    else:
        # * Re-render the previous results without re-running the query.
        previous_query = (
            ctx.user_data.get("stats_last_query", "") if ctx.user_data else ""
        )
        await _ack_and_render(q, Stats.search_results(previous_query, results))


@decorators.ratelimiter(limit=15, period=30)
@decorators.log_execution
async def on_stats_search_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Clear the active search and return to the first page of the ban list."""
    q = update.callback_query
    Stats.clear_search(ctx)
    await _ack_and_render(q, Stats.bans_list(0))


# ──────────────────────────── Handlers ──────────────────────────── #

_STATS_CMDS = build_prefixed_filters("tcstats") | build_prefixed_filters("tcs")

__handlers__ = [
    MessageHandler(_STATS_CMDS, cmd_stats),
    CallbackQueryHandler(on_stats_main, pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins$"),
    CallbackQueryHandler(on_stats_users, pattern=r"^stats_users:\d+$"),
    CallbackQueryHandler(on_stats_user_item, pattern=r"^stats_user_item:\d+:\d+$"),
    CallbackQueryHandler(on_stats_chats, pattern=r"^stats_chats:\d+$"),
    CallbackQueryHandler(on_stats_chat_item, pattern=r"^stats_chat_item:\d+:\d+$"),
    CallbackQueryHandler(on_stats_bans, pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(on_stats_ban_item, pattern=r"^stats_ban_item:\d+:\d+$"),
    CallbackQueryHandler(on_stats_bans_search, pattern=r"^stats_bans_search$"),
    CallbackQueryHandler(on_stats_search_item, pattern=r"^stats_search_item:\d+$"),
    CallbackQueryHandler(on_stats_search_back, pattern=r"^stats_search_back$"),
    CallbackQueryHandler(on_stats_search_cancel, pattern=r"^stats_search_cancel$"),
    # * Scoped to private chat: search input is only meaningful in PM where the
    # * user opened the bans panel. Avoids absorbing every non-command text in
    # * groups.
    MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
        on_bans_search_input,
    ),
]
