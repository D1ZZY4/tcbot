# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban search panel: prompt state, query resolution, and result cards."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from telegram import CallbackQuery, InlineKeyboardMarkup, Message

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.keyboards import (
    back_to_module_kb,
    detail_kb,
    stats_search_panel_kb,
    stats_search_results_kb,
)
from tcbot.modules.helper.workflows.stats_flow.shared import (
    _SEARCH_LIMIT,
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
)
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

    from tcbot.database.documents import BanDoc


class SearchViews:
    """Search prompt lifecycle and result rendering for active bans."""

    @staticmethod
    def _search_panel_kb(locale: str | None = None) -> InlineKeyboardMarkup:
        """Search panel keyboard (single source: keyboards)."""
        return stats_search_panel_kb(locale)

    @staticmethod
    def _search_results_kb(
        n: int, locale: str | None = None, *, item_ids: list[str] | None = None
    ) -> InlineKeyboardMarkup:
        """Numbered search results (single source: keyboards)."""
        return stats_search_results_kb(n, locale, item_ids=item_ids)

    @classmethod
    def open_search(
        cls,
        ctx: ContextTypes.DEFAULT_TYPE,
        q: CallbackQuery,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Open the search prompt; remember chat/message so input edits the right card.

        When the callback carries no accessible message (inline-message edge),
        the prompt still renders but no card IDs are stored, so a later search
        input degrades to a no-op edit instead of crashing on ``None``.
        """
        text = t("stats.search.title", locale)
        msg = q.message
        if not isinstance(msg, Message):
            return text, cls._search_panel_kb(locale)
        ud = cast("dict[str, object]", ctx.user_data)
        ud[SEARCH_KEY] = True
        ud[MSG_KEY] = msg.message_id
        ud[CHAT_KEY] = msg.chat_id
        return text, cls._search_panel_kb(locale)

    @staticmethod
    def clear_search(ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Forget any in-flight search context."""
        ud = cast("dict[str, object]", ctx.user_data)
        for key in (SEARCH_KEY, RESULTS_KEY, MSG_KEY, CHAT_KEY, "stats_last_query"):
            ud.pop(key, None)

    @classmethod
    async def search_run(cls, query: str) -> list[BanDoc]:
        """Resolve a search query against active bans (ID or name match).

        Name matching is server-side: an anchored prefix lookup in the
        member cache (same semantics as target resolution), capped at
        ``_SEARCH_LIMIT`` hits, then a single ``$in`` fetch of their
        active bans. Never loads the whole ban list.
        """
        q = query.strip()
        if q.isdigit():
            ban = await db.bans_db.get_active_ban(int(q))
            return [ban] if ban else []

        matches = await db.users_cache.search_by_name(q, limit=_SEARCH_LIMIT)
        if not matches:
            return []
        uids = [u.get("user_id", 0) for u in matches if u.get("user_id")]
        return await db.bans_db.active_bans_for_users(uids)

    @classmethod
    async def search_results(
        cls,
        query: str,
        results: list[BanDoc],
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Render search results: empty state or numbered hits."""
        if not results:
            text = t("stats.search.empty", locale, query=query)
            return text, cls._search_results_kb(0, locale)
        uids = [b.get("banned_user_id", 0) for b in results]
        fname_map = await db.users_cache.get_first_names_batch(uids)
        lines = [t("stats.search.header", locale, query=query, n=len(results)) + "\n"]
        for i, ban in enumerate(results, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(
                t(
                    "stats.search.item",
                    locale,
                    i=i,
                    name=fname,
                    id=Safe(code(str(uid))),
                )
            )
        return "\n".join(lines), cls._search_results_kb(
            len(results),
            locale,
            item_ids=[str(ban.get("ban_id", "")) for ban in results],
        )

    @classmethod
    async def search_detail(
        cls,
        results: list[BanDoc],
        idx: int,
        locale: str | None = None,
        stable: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single search hit.

        When ``stable`` carries the ban ID embedded in the tapped button,
        the record at ``idx`` must still carry it; a list mutation between
        render and tap otherwise shows the wrong ban.
        """
        if idx < 0 or idx >= len(results):
            text = t("stats.error.result_unavailable", locale)
            kb = back_to_module_kb("stats_search_back")
            return text, kb
        ban = results[idx]
        if stable is not None and str(ban.get("ban_id", "")) != stable:
            text = t("stats.error.result_unavailable", locale)
            kb = back_to_module_kb("stats_search_back")
            return text, kb
        text, proof_link = await build_ban_detail(ban, locale=locale)
        return text, detail_kb(
            back_callback="stats_search_back",
            proof_link=proof_link,
            locale=locale,
        )
