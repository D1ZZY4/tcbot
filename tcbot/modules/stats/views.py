# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Drill-down callbacks: roster, users, chats, and bans views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import ack_and_render
from tcbot.modules.helper.workflows.stats_flow import Stats
from tcbot.modules.stats.command import (
    _RL_CB_LIMIT,
    _RL_PERIOD_S,
    _parse_item_callback,
    _require_founder_list,
)

if TYPE_CHECKING:
    from telegram import Update


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level stats menu."""
    q = update.callback_query
    if q is None:
        return
    tapper = update.effective_user
    await ack_and_render(
        q,
        Stats.main(
            viewer_id=tapper.id if tapper is not None else None,
            locale=await locale_for_update(update),
        ),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the current staff roster page."""
    q = update.callback_query
    if q is None:
        return
    await ack_and_render(q, Stats.staff_roster(await locale_for_update(update)))


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of cached users."""
    q = update.callback_query
    if q is None:
        return
    try:
        page = int((q.data or "").split(":")[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    tapper = update.effective_user
    if not await _require_founder_list(
        q, tapper.id if tapper is not None else None, update
    ):
        return
    await ack_and_render(q, Stats.users_list(page, await locale_for_update(update)))


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_user_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single cached user entry."""
    q = update.callback_query
    if q is None:
        return
    parsed = _parse_item_callback(q)
    if parsed is None:
        await q.answer()
        return
    page, idx, stable = parsed
    tapper = update.effective_user
    if not await _require_founder_list(
        q, tapper.id if tapper is not None else None, update
    ):
        return
    await ack_and_render(
        q,
        Stats.user_detail(ctx.bot, page, idx, stable, await locale_for_update(update)),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of connected groups."""
    q = update.callback_query
    if q is None:
        return
    try:
        page = int((q.data or "").split(":")[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    await ack_and_render(q, Stats.chats_list(page, await locale_for_update(update)))


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_chat_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single connected group entry."""
    q = update.callback_query
    if q is None:
        return
    parsed = _parse_item_callback(q)
    if parsed is None:
        await q.answer()
        return
    page, idx, stable = parsed
    await ack_and_render(
        q,
        Stats.chat_detail(ctx.bot, page, idx, stable, await locale_for_update(update)),
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated ban-list page and clear any active search state."""
    q = update.callback_query
    if q is None:
        return
    try:
        page = int((q.data or "").split(":")[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(page, await locale_for_update(update)))


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_stats_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single ban entry from the stats list."""
    q = update.callback_query
    if q is None:
        return
    parsed = _parse_item_callback(q)
    if parsed is None:
        await q.answer()
        return
    page, idx, stable = parsed
    await ack_and_render(
        q, Stats.ban_detail(page, idx, stable, await locale_for_update(update))
    )
