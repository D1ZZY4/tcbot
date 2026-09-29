# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared tunables, search keys, refresh tasks, and keyboard aliases."""

from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.keyboards import (
    stats_back_kb,
    stats_back_row,
    stats_list_kb,
    stats_main_kb,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)

_PAGE_SIZE = 6

# * Bounds the $in fetch and the per-user search-result state in user_data.
_SEARCH_LIMIT = 30

# * Search panel state on ctx.user_data, shared by callbacks and the input fallback.
SEARCH_KEY = "stats_search_active"
RESULTS_KEY = "stats_search_results"
MSG_KEY = "stats_search_msg_id"
CHAT_KEY = "stats_search_chat_id"

# * Stats runtime prose lives in stats.toml; only tunables stay in code.

# * Strong refs to in-flight refresh tasks; prevents GC before completion.
_refresh_tasks: set[asyncio.Task[None]] = set()


async def _refresh_group_title(bot: Bot, chat_id: int) -> None:
    """Verify a group title live and persist renames (background, best-effort)."""
    try:
        live_chat = await asyncio.wait_for(
            bot.get_chat(chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        )
    except Exception as exc:
        log.debug("background title check failed for %d: %s", chat_id, exc)
        return
    if live_chat is None or not live_chat.title:
        return
    try:
        await db.groups_db.refresh_group_title(chat_id, live_chat.title)
    except Exception as exc:
        log.debug("background title refresh failed for %d: %s", chat_id, exc)


def launch_group_title_refresh(bot: Bot, chat_id: int) -> None:
    """Fire-and-forget group title sync for detail views (zero added latency)."""
    try:
        task = asyncio.get_running_loop().create_task(
            _refresh_group_title(bot, chat_id)
        )
    except RuntimeError:
        log.debug("group title refresh skipped: no running event loop.")
        return
    _refresh_tasks.add(task)
    task.add_done_callback(_refresh_tasks.discard)


def _back_main(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Back row to the stats main menu (single source: keyboards)."""
    return stats_back_row(locale)


def main_kb(
    *, show_users: bool = False, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Top-level ``/tcstats`` menu: Staff / Bans / Chats drill-downs.

    The ``Users`` list carries every cached user ID, so its button is shown
    only to the Owner/Founder (row 3); everyone else gets rows 1-2 only.
    The ``stats_users`` callbacks enforce the same gate, so a stale or
    crafted tap without the button still cannot open the list.
    """
    return stats_main_kb(show_users=show_users, locale=locale)


def back_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the stats main menu."""
    return stats_back_kb(locale)


def _list_kb(
    page: int,
    total_pages: int,
    n_items: int,
    cb_prefix: str,
    item_cb_prefix: str,
    *,
    extra_row: list[InlineKeyboardButton] | None = None,
    item_ids: list[str] | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Compose nav + numbered detail buttons + optional extra row + back.

    ``item_ids`` carries one stable entity ID per button (user ID, chat ID,
    or ban ID). Detail handlers verify the resolved record still carries
    that ID so a list mutation between render and tap cannot silently show
    a different record. Older buttons without the segment keep working.
    """
    return stats_list_kb(
        page,
        total_pages,
        n_items,
        cb_prefix,
        item_cb_prefix,
        extra_row=extra_row,
        item_ids=item_ids,
        locale=locale,
    )
