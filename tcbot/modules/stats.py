# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""``/tcstats`` command and callback handlers: federation-wide overview and drill-downs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pyrogram import filters
from pyrogram.types import CallbackQuery, Message

from tcbot.modules.helper import decorators, guards
from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.handlers import CallbackQueryHandler, MessageHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    ack_and_render,
    answer_alert,
    answer_and_edit,
    callback_numbers,
    replies,
    reply_rich,
    safe_edit_message,
    send_text,
)
from tcbot.modules.helper.pipelines.stats_panels import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    Stats,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

if TYPE_CHECKING:
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
        await answer_alert(q, t("stats.error.access_retry", locale, plain=True))
        return False
    if access is not guards.StaffAccess.ALLOWED:
        await answer_alert(q, denial)
        return False
    return True


async def _require_owner_list(
    q: CallbackQuery, user_id: int | None, ctx: Ctx
) -> str | None:
    """Return the render locale when the tapper may open the Users list.

    Owner only: the list carries every cached user ID. A denied
    tapper gets the Owner-only alert and ``None``. Lookup outages fail
    closed with a retry alert; cancellation propagates.
    """
    locale = await locale_for_update(ctx)
    allowed = await _pane_access(
        q,
        user_id,
        locale,
        min_role="owner",
        denial=replies.perm_owner_only(locale, plain=True),
    )
    return locale if allowed else None


async def _require_staff_pane(q: CallbackQuery, ctx: Ctx) -> str | None:
    """Return the render locale when the tapper may open a staff pane.

    The staff roster, the connected-group list, and the federation ban
    list enumerate federation-wide records, so they stay behind the staff
    gate. The overview counts stay public. A denied tapper gets the
    staff-only alert and ``None``.
    """
    tapper = ctx.effective_user
    locale = await locale_for_update(ctx)
    allowed = await _pane_access(
        q,
        tapper.id if tapper is not None else None,
        locale,
        min_role="moderator",
        denial=t("stats.error.staff_only", locale, plain=True),
    )
    return locale if allowed else None


async def _require_staff_input(msg: Message, ctx: Ctx) -> str | None:
    """Return the render locale when the sender may run the ban search.

    The free-text search reads the federation ban list, so it carries the
    same gate as the ban pane it belongs to. The notice is a plain reply
    because the input path has no callback query to alert on.
    """
    tapper = ctx.effective_user
    locale = await locale_for_update(ctx)
    access = await guards.staff_access(
        tapper.id if tapper is not None else None, min_role="moderator"
    )
    if access is guards.StaffAccess.LOOKUP_FAILED:
        await reply_rich(
            msg,
            t("stats.error.access_retry", locale, plain=True),
            log_label="stats search access-fail",
            parse_mode=None,
        )
        return None
    if access is not guards.StaffAccess.ALLOWED:
        await reply_rich(
            msg,
            t("stats.error.staff_only", locale, plain=True),
            log_label="stats search staff-only",
            parse_mode=None,
        )
        return None
    return locale


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_stats(ctx: Ctx) -> None:
    """Send the federation overview message."""
    msg = ctx.effective_message
    if msg is None:
        return
    user = ctx.effective_user
    text, btn = await Stats.main(
        viewer_id=user.id if user is not None else None,
        locale=await locale_for_update(ctx),
    )
    await reply_rich(msg, text, log_label="cmd_stats", reply_markup=btn)


# ────────────────────────── Search callbacks ───────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_bans_search(ctx: Ctx) -> None:
    """Open the user search prompt within the stats ban view."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
    if locale is None:
        return
    text, btn = Stats.open_search(ctx, q, locale)
    await answer_and_edit(q, text, reply_markup=btn)


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_bans_search_input(ctx: Ctx) -> None:
    """Free-text query message handler; only reacts when the search panel is active."""
    if ctx.user_data is None or not ctx.user_data.get(SEARCH_KEY):
        return
    msg = ctx.effective_message
    if msg is None:
        return
    locale = await _require_staff_input(msg, ctx)
    if locale is None:
        ctx.user_data.pop(SEARCH_KEY, None)
        return
    ctx.user_data.pop(SEARCH_KEY, None)
    # * The panel card may live in another chat; only the stored panel chat
    # * accepts input, so a message elsewhere is neither deleted nor rendered
    # * into the wrong card. Pending state stays for the right chat.
    panel_chat = ctx.user_data.get(CHAT_KEY)
    if panel_chat is not None and chat_id_of(msg.chat) != panel_chat:
        ctx.user_data[SEARCH_KEY] = True
        return
    query = (msg.text or "").strip()

    results, _deleted = await asyncio.gather(
        Stats.search_run(query),
        msg.delete(),
        return_exceptions=True,
    )
    throw_if_cancelled((results, _deleted))
    if isinstance(results, BaseException):
        # * An outage must not render as "no bans match this query": the
        # * operator would read a failed search as a clean result.
        # * The query is member-authored text. ERROR records reach the staff
        # * channel, so log its shape rather than its contents.
        log.error(
            "Stats search failed for a %d-character query: %s", len(query), results
        )
        await _search_notice(ctx, msg, locale)
        return

    try:
        text, btn = await Stats.search_results(query, results, locale)
    except asyncio.CancelledError:
        raise
    except Exception:
        # * A DB failure while rendering the found rows is the same outage as
        # * a failed lookup. Without this branch the open-search prompt stayed
        # * on screen and further text was ignored because SEARCH_KEY was gone.
        log.exception("Stats search render failed for a %d-character query", len(query))
        await _search_notice(ctx, msg, locale)
        return

    ctx.user_data[RESULTS_KEY] = results
    ctx.user_data["stats_last_query"] = query

    chat_id = ctx.user_data.get(CHAT_KEY)
    msg_id = ctx.user_data.get(MSG_KEY)
    edited = False
    if chat_id is not None and msg_id is not None:
        edited = await safe_edit_message(
            ctx.bot,
            chat_id,
            msg_id,
            text,
            reply_markup=btn,
            log_level="debug",
            log_label="Stats search result",
            catch_all=True,
        )
    if not edited:
        # * A missing or stale panel message makes the edit return False. The
        # * query message is already deleted, so send results to its chat
        # * instead of dropping them with no response at all.
        try:
            await send_text(ctx.bot, chat_id_of(msg.chat), text, reply_markup=btn)
        except Exception as exc:
            log.debug("Stats search result fallback failed: %s", exc)


async def _search_notice(ctx: Ctx, msg: Message, locale: str) -> None:
    """Deliver the search failure notice to the open panel or its chat."""
    user_data = ctx.user_data or {}
    chat_id = user_data.get(CHAT_KEY)
    msg_id = user_data.get(MSG_KEY)
    if chat_id is not None and msg_id is not None:
        updated = await safe_edit_message(
            ctx.bot,
            chat_id,
            msg_id,
            t("stats.error.db_fail", locale),
            log_level="debug",
            log_label="Stats search error",
            catch_all=True,
        )
        if updated:
            return
    try:
        await send_text(
            ctx.bot, chat_id_of(msg.chat), t("stats.error.db_fail", locale, plain=True)
        )
    except Exception as exc:
        log.debug("Stats search error notice failed: %s", exc)


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_search_back(ctx: Ctx) -> None:
    """Return to search results (or the open-search prompt) without re-running the query."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
    if locale is None:
        return
    results = ctx.user_data.get(RESULTS_KEY, []) if ctx.user_data else []
    if not results:
        text, btn = Stats.open_search(ctx, q, locale)
        await answer_and_edit(q, text, reply_markup=btn)
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
async def on_stats_search_cancel(ctx: Ctx) -> None:
    """Clear the active search and return to the first page of the ban list."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
    if locale is None:
        return
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(0, locale))


# ────────────────────────── Drill-down callbacks ───────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_main(ctx: Ctx) -> None:
    """Render the top-level stats menu."""
    q = ctx.callback_query
    if q is None:
        return
    tapper = ctx.effective_user
    await ack_and_render(
        q,
        Stats.main(
            viewer_id=tapper.id if tapper is not None else None,
            locale=await locale_for_update(ctx),
        ),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_admins(ctx: Ctx) -> None:
    """Render the current staff roster page."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
    if locale is None:
        return
    await ack_and_render(q, Stats.staff_roster(locale, bot=ctx.bot))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_users(ctx: Ctx) -> None:
    """Render a paginated list of cached users."""
    q = ctx.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    page = numbers[0]
    tapper = ctx.effective_user
    locale = await _require_owner_list(
        q, tapper.id if tapper is not None else None, ctx
    )
    if locale is None:
        return
    await ack_and_render(q, Stats.users_list(page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_stats_chats(ctx: Ctx) -> None:
    """Render a paginated list of connected groups."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
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
async def on_stats_bans(ctx: Ctx) -> None:
    """Render a paginated ban-list page and clear any active search state."""
    q = ctx.callback_query
    if q is None:
        return
    locale = await _require_staff_pane(q, ctx)
    if locale is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    page = numbers[0]
    Stats.clear_search(ctx)
    await ack_and_render(q, Stats.bans_list(page, locale))


# ──────────────────────────── Handlers ──────────────────────────── #

_STATS_CMDS = build_prefixed_filters("tcstats") | build_prefixed_filters("tcs")


def _deferred_message_handler(filter_, callback):
    """Register a free-text handler in a later Kurigram group."""
    handler = MessageHandler(filter_, callback)
    # * Kurigram handlers have no declared group attribute; the registry reads
    # * this label with getattr. Use object.__setattr__ so both the type checker
    # * and Ruff agree that this is an intentional dynamic registration label.
    object.__setattr__(handler, "handler_group", 5)
    return handler


# * The search prompt consumes free text in its own group. In group 0 it
# * would be registered before the later-sorted warn conversation and swallow
# * the reason the moderator types after /tcwarn.
_search_input_handler = _deferred_message_handler(
    filters.text & ~ALL_PREFIXES_CMD_FILTER,
    on_bans_search_input,
)

__handlers__ = [
    MessageHandler(_STATS_CMDS, cmd_stats),
    CallbackQueryHandler(on_stats_main, pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins$"),
    CallbackQueryHandler(on_stats_users, pattern=r"^stats_users:\d+$"),
    CallbackQueryHandler(on_stats_chats, pattern=r"^stats_chats:\d+$"),
    CallbackQueryHandler(on_stats_bans, pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(on_stats_bans_search, pattern=r"^stats_bans_search$"),
    CallbackQueryHandler(on_stats_search_back, pattern=r"^stats_search_back$"),
    CallbackQueryHandler(on_stats_search_cancel, pattern=r"^stats_search_cancel$"),
    # * Registered in every chat because the panel can be opened from a
    # * group. Its own Kurigram group keeps it behind group-0 conversations; it
    # * also returns immediately unless SEARCH_KEY is set and the message
    # * comes from the chat that owns the panel.
    _search_input_handler,
]
