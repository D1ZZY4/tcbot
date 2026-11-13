# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""``/tcstats`` command and callback handlers: federation-wide overview and drill-downs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tcbot.modules.helper import decorators, guards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    ack_and_render,
    answer_and_edit,
    callback_args_optional,
    callback_numbers,
    replies,
    safe_edit_message,
    safe_reply,
)
from tcbot.modules.helper.pipelines.stats_flow import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    Stats,
)
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

if TYPE_CHECKING:
    from telegram import CallbackQuery, Message, Update

    from tcbot.database.users_roles import RoleName

log = get_logger(__name__)


__module_name__ = "Stats"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("stats.help.overview", locale),
        commands=t("stats.help.commands.body", locale),
        who=replies.context_anyone(locale),
        where=replies.context_bot_or_group(locale),
        what=t("stats.help.what.body", locale),
        target=False,
        details=[
            (
                t("stats.help.drills.title", locale, plain=True),
                t("stats.help.drills.body", locale),
            )
        ],
        examples=t("stats.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()


# ────────────────────────── Command entry ────────────────────────── #


async def _alert(q: CallbackQuery, text: str) -> None:
    """Answer the callback query with an alert, ignoring a failed answer."""
    try:
        await q.answer(text, show_alert=True)
    except Exception as exc:
        log.debug("stats pane deny-answer failed: %s", exc)


async def _pane_access(
    q: CallbackQuery,
    user_id: int | None,
    locale: str,
    *,
    min_role: RoleName,
    denial: str,
) -> bool:
    """Return True when the tapper may open a gated stats pane.

    ``min_role`` names the lowest rank that passes; the shared gate owns
    the comparison so the rank table stays the single source of truth.

    A lookup outage fails closed with a retry alert; cancellation
    propagates.
    """
    access = await guards.staff_access(user_id, min_role=min_role)
    if access is guards.StaffAccess.LOOKUP_FAILED:
        await _alert(q, t("stats.error.access_retry", locale, plain=True))
        return False
    if access is not guards.StaffAccess.ALLOWED:
        await _alert(q, denial)
        return False
    return True


async def _require_founder_list(
    q: CallbackQuery, user_id: int | None, update: Update
) -> str | None:
    """Return the render locale when the tapper may open the Users list.

    Owner-or-Founder only: the list carries every cached user ID. A denied
    tapper gets the Founder-only alert and ``None``. Lookup outages fail
    closed with a retry alert; cancellation propagates.
    """
    locale = await locale_for_update(update)
    allowed = await _pane_access(
        q,
        user_id,
        locale,
        min_role="founder",
        denial=replies.perm_founder_only(locale, plain=True),
    )
    return locale if allowed else None


async def _require_staff_pane(q: CallbackQuery, update: Update) -> str | None:
    """Return the render locale when the tapper may open a staff pane.

    The staff roster, the connected-group list, and the federation ban
    list enumerate federation-wide records, so they stay behind the staff
    gate. The overview counts stay public. A denied tapper gets the
    staff-only alert and ``None``.
    """
    tapper = update.effective_user
    locale = await locale_for_update(update)
    allowed = await _pane_access(
        q,
        tapper.id if tapper is not None else None,
        locale,
        min_role="tester",
        denial=t("stats.error.staff_only", locale, plain=True),
    )
    return locale if allowed else None


async def _require_staff_input(msg: Message, update: Update) -> str | None:
    """Return the render locale when the sender may run the ban search.

    The free-text search reads the federation ban list, so it carries the
    same gate as the ban pane it belongs to. The notice is a plain reply
    because the input path has no callback query to alert on.
    """
    tapper = update.effective_user
    locale = await locale_for_update(update)
    access = await guards.staff_access(
        tapper.id if tapper is not None else None, min_role="tester"
    )
    if access is guards.StaffAccess.LOOKUP_FAILED:
        await safe_reply(
            msg,
            t("stats.error.access_retry", locale, plain=True),
            log_label="stats search access-fail",
            parse_mode=None,
        )
        return None
    if access is not guards.StaffAccess.ALLOWED:
        await safe_reply(
            msg,
            t("stats.error.staff_only", locale, plain=True),
            log_label="stats search staff-only",
            parse_mode=None,
        )
        return None
    return locale


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the federation overview message."""
    msg = update.effective_message
    if msg is None:
        return
    user = update.effective_user
    text, kb = await Stats.main(
        viewer_id=user.id if user is not None else None,
        locale=await locale_for_update(update),
    )
    await safe_reply(msg, text, log_label="cmd_stats", reply_markup=kb)


def _parse_item_callback(
    q: CallbackQuery,
) -> tuple[int, int, str | None] | None:
    """Parse ``prefix:page:idx[:stable]`` item callbacks.

    Four-part callbacks carry the stable entity ID so detail views can
    reject a record shifted by a concurrent list mutation. Three-part
    callbacks from older keyboards keep working without the check.
    """
    args = callback_args_optional(q, 3)
    if args is None:
        return None
    try:
        page, idx = int(args[0]), int(args[1])
    except ValueError:
        return None
    stable = args[2] if len(args) > 2 else None
    return page, idx, stable


# ────────────────────────── Search callbacks ───────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the user search prompt within the stats ban view."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    text, kb = Stats.open_search(ctx, q, locale)
    await answer_and_edit(q, text, reply_markup=kb)


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text query message handler; only reacts when the search panel is active."""
    if ctx.user_data is None or not ctx.user_data.get(SEARCH_KEY):
        return
    msg = update.effective_message
    if msg is None:
        return
    locale = await _require_staff_input(msg, update)
    if locale is None:
        ctx.user_data.pop(SEARCH_KEY, None)
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
    text, kb = await Stats.search_results(query, results, locale)
    if chat_id is not None and msg_id is not None:
        await safe_edit_message(
            ctx.bot,
            chat_id,
            msg_id,
            text,
            reply_markup=kb,
            log_level="debug",
            log_label="Stats search result",
            catch_all=True,
        )
    else:
        # * No result card to edit: reply with results instead of dropping them.
        await safe_reply(
            msg, text, log_label="Stats search result fallback", reply_markup=kb
        )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_search_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a search result selected by the user."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    args = callback_args_optional(q, 2)
    if args is None:
        await q.answer()
        return
    try:
        idx = int(args[0])
    except ValueError:
        await q.answer()
        return
    stable = args[1] if len(args) > 1 else None
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    await ack_and_render(q, Stats.search_detail(results, idx, locale, stable))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_search_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to search results (or the open-search prompt) without re-running the query."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    if not results:
        text, kb = Stats.open_search(ctx, q, locale)
        await answer_and_edit(q, text, reply_markup=kb)
    else:
        previous_query = (
            ctx.user_data.get("stats_last_query", "") if ctx.user_data else ""
        )
        await ack_and_render(
            q,
            Stats.search_results(previous_query, results, locale),
        )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_search_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Clear the active search and return to the first page of the ban list."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(0, locale))


# ────────────────────────── Drill-down callbacks ───────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
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


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the current staff roster page."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    await ack_and_render(q, Stats.staff_roster(locale, bot=ctx.bot))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of cached users."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    page = numbers[0]
    tapper = update.effective_user
    locale = await _require_founder_list(
        q, tapper.id if tapper is not None else None, update
    )
    if locale is None:
        return
    await ack_and_render(q, Stats.users_list(page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
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
    locale = await _require_founder_list(
        q, tapper.id if tapper is not None else None, update
    )
    if locale is None:
        return
    await ack_and_render(
        q,
        Stats.user_detail(ctx.bot, page, idx, stable, locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of connected groups."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    page = numbers[0]
    await ack_and_render(q, Stats.chats_list(page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_chat_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single connected group entry."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    parsed = _parse_item_callback(q)
    if parsed is None:
        await q.answer()
        return
    page, idx, stable = parsed
    await ack_and_render(
        q,
        Stats.chat_detail(ctx.bot, page, idx, stable, locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated ban-list page and clear any active search state."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    page = numbers[0]
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the detail view for a single ban entry from the stats list."""
    q = update.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, update)
    if locale is None:
        return
    parsed = _parse_item_callback(q)
    if parsed is None:
        await q.answer()
        return
    page, idx, stable = parsed
    await ack_and_render(q, Stats.ban_detail(page, idx, stable, locale))


# ──────────────────────────── Handlers ──────────────────────────── #

_STATS_CMDS = build_prefixed_filters("tcstats") | build_prefixed_filters("tcs")

__handlers__ = [
    MessageHandler(_STATS_CMDS, cmd_stats),
    CallbackQueryHandler(on_stats_main, pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins$"),
    CallbackQueryHandler(on_stats_users, pattern=r"^stats_users:\d+$"),
    CallbackQueryHandler(
        on_stats_user_item, pattern=r"^stats_user_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_chats, pattern=r"^stats_chats:\d+$"),
    CallbackQueryHandler(
        on_stats_chat_item, pattern=r"^stats_chat_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_bans, pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(
        on_stats_ban_item, pattern=r"^stats_ban_item:\d+:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_bans_search, pattern=r"^stats_bans_search$"),
    CallbackQueryHandler(
        on_stats_search_item, pattern=r"^stats_search_item:\d+(:[^:]+)?$"
    ),
    CallbackQueryHandler(on_stats_search_back, pattern=r"^stats_search_back$"),
    CallbackQueryHandler(on_stats_search_cancel, pattern=r"^stats_search_cancel$"),
    # * Search input only matters in PM where the bans panel was opened;
    # * avoids absorbing every non-command text in groups.
    MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
        on_bans_search_input,
    ),
]
