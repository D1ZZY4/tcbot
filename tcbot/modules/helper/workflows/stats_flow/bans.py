# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Active federation ban list and detail views."""

from __future__ import annotations

import asyncio

from telegram import InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.keyboards import (
    back_to_module_kb,
    detail_kb,
    stats_search_row,
)
from tcbot.modules.helper.workflows.stats_flow.shared import (
    _PAGE_SIZE,
    _list_kb,
    back_kb,
)
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


class BanViews:
    """Paginated active-ban roster and single-ban detail cards."""

    @classmethod
    async def bans_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active federation ban."""
        # * Server-side count + page fetch; a read outage renders a retry card.
        try:
            total = await db.bans_db.active_ban_count()
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            page = max(0, min(page, total_pages - 1))
            chunk = await db.bans_db.active_bans_page(page * _PAGE_SIZE, _PAGE_SIZE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats bans_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)

        if total == 0:
            return t("stats.bans_view.empty", locale), back_kb(locale)

        uids = [b.get("banned_user_id", 0) for b in chunk]
        fname_map = await db.users_cache.get_first_names_batch(uids) if uids else {}

        lines = [
            t(
                "stats.bans_view.header",
                locale,
                n=total,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(
                t(
                    "stats.bans_view.item",
                    locale,
                    i=base_idx + i,
                    name=fname,
                    id=Safe(code(str(uid))),
                )
            )

        search_row = stats_search_row(locale)
        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_bans",
            item_cb_prefix="stats_ban_item",
            extra_row=search_row,
            item_ids=[str(ban.get("ban_id", "")) for ban in chunk],
            locale=locale,
        )

    @classmethod
    async def ban_detail(
        cls,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a banned user, reusing ``build_ban_detail``.

        The record is fetched directly by stable ban ID (one indexed read)
        instead of re-reading the whole active-ban list: faster and immune
        to list shifts between render and tap. Inactive or missing records
        still report not-found.
        """
        if stable is not None:
            ban = await db.bans_db.get_ban(stable)
            if not ban or not ban.get("is_active"):
                text = t("stats.error.ban_not_found", locale)
                kb = back_to_module_kb(f"stats_bans:{page}", locale)
                return text, kb
            text, proof_link = await build_ban_detail(ban, locale=locale)
            return text, detail_kb(
                back_callback=f"stats_bans:{page}",
                proof_link=proof_link,
                locale=locale,
            )
        return (
            t("stats.error.ban_not_found", locale),
            back_to_module_kb(f"stats_bans:{page}", locale),
        )
