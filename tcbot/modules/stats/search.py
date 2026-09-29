# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban search panel callbacks and free-text input handling."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import (
    ack_and_render,
    answer_and_edit,
    safe_reply,
)
from tcbot.modules.helper.workflows.stats_flow import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    Stats,
)
from tcbot.modules.stats.command import _RL_CB_LIMIT, _RL_PERIOD_S
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the user search prompt within the stats ban view."""
    q = update.callback_query
    if q is None:
        return
    text, kb = Stats.open_search(ctx, q, await locale_for_update(update))
    await answer_and_edit(q, text, reply_markup=kb)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text query message handler; only reacts when the search panel is active."""
    if ctx.user_data is None or not ctx.user_data.get(SEARCH_KEY):
        return
    msg = update.effective_message
    if msg is None:
        return
    ctx.user_data.pop(SEARCH_KEY, None)
    # * The panel card may live in another chat; only the stored panel chat
    # * accepts input, so a message elsewhere is neither deleted nor rendered
    # * into the wrong card. Pending state stays for the right chat.
    panel_chat = ctx.user_data.get(CHAT_KEY)
    if panel_chat is not None and msg.chat_id != panel_chat:
        ctx.user_data[SEARCH_KEY] = True
        return
    query = (msg.text or "").strip()

    results, _ = await asyncio.gather(
        Stats.search_run(query),
        msg.delete(),
        return_exceptions=True,
    )
    if isinstance(results, BaseException):
        results = []

    ctx.user_data[RESULTS_KEY] = results
    ctx.user_data["stats_last_query"] = query

    chat_id = ctx.user_data.get(CHAT_KEY)
    msg_id = ctx.user_data.get(MSG_KEY)
    text, kb = await Stats.search_results(
        query, results, await locale_for_update(update)
    )
    if chat_id is not None and msg_id is not None:
        try:
            await ctx.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="MarkdownV2",
                reply_markup=kb,
            )
        except Exception as exc:
            log.debug("Stats search result edit failed: %s", exc)
    else:
        # * No result card to edit: reply with results instead of dropping them.
        await safe_reply(
            msg, text, log_label="Stats search result fallback", reply_markup=kb
        )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_search_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a search result selected by the user."""
    q = update.callback_query
    if q is None:
        return
    parts = (q.data or "").split(":")
    try:
        idx = int(parts[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    stable = parts[2] if len(parts) > 2 else None
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    await ack_and_render(
        q, Stats.search_detail(results, idx, await locale_for_update(update), stable)
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_search_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to search results (or the open-search prompt) without re-running the query."""
    q = update.callback_query
    if q is None:
        return
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    if not results:
        text, kb = Stats.open_search(ctx, q, await locale_for_update(update))
        await answer_and_edit(q, text, reply_markup=kb)
    else:
        previous_query = (
            ctx.user_data.get("stats_last_query", "") if ctx.user_data else ""
        )
        await ack_and_render(
            q,
            Stats.search_results(
                previous_query, results, await locale_for_update(update)
            ),
        )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_search_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Clear the active search and return to the first page of the ban list."""
    q = update.callback_query
    if q is None:
        return
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(0, await locale_for_update(update)))
