# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cached member roster list and detail views."""

from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.keyboards import back_to_module_kb
from tcbot.modules.helper.workflows.stats_flow.shared import (
    _PAGE_SIZE,
    _list_kb,
    back_kb,
)
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import date_or_unknown

log = get_logger(__name__)


class PeopleViews:
    """Paginated member roster and single-user detail cards."""

    @classmethod
    async def users_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every cached user."""
        # * Server-side count + page fetch; a read outage renders a retry card.
        try:
            total = await db.users_cache.total_users()
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            page = max(0, min(page, total_pages - 1))
            chunk = await db.users_cache.all_users_page(
                skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats users_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)

        if total == 0:
            return t("stats.users.empty", locale), back_kb(locale)

        lines = [
            t(
                "stats.users.header",
                locale,
                n=total,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, u in enumerate(chunk, start=1):
            uid = u.get("user_id", 0)
            fname = u.get("first_name") or str(uid)
            uname = u.get("username")
            lines.append(
                t(
                    "stats.users.item",
                    locale,
                    i=base_idx + i,
                    user=Safe(user_ref(uid, fname, uname)),
                )
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_users",
            item_cb_prefix="stats_user_item",
            item_ids=[str(u.get("user_id", 0)) for u in chunk],
            locale=locale,
        )

    @classmethod
    async def user_detail(
        cls,
        bot: Bot,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single cached user, with a link back into the list page."""
        chunk = await db.users_cache.all_users_page(
            skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
        )
        if idx < 0 or idx >= len(chunk):
            text = t("stats.error.user_not_found", locale)
            kb = back_to_module_kb(f"stats_users:{page}", locale)
            return text, kb

        u = chunk[idx]
        uid = u.get("user_id", 0)
        if stable is not None and str(uid) != stable:
            text = t("stats.error.user_not_found", locale)
            kb = back_to_module_kb(f"stats_users:{page}", locale)
            return text, kb
        fname = u.get("first_name") or str(uid)
        uname = u.get("username")
        last_name = u.get("last_name") or "-"
        # * Stale-while-revalidate: render from cache, refresh in background.
        if identity_needs_refresh(u):
            launch_identity_refresh(bot, uid)
        commit = date_or_unknown(u.get("commit_date"), locale)
        seen = date_or_unknown(u.get("last_updated"), locale)

        if uname:
            username_line = t("stats.user_detail.username", locale, name=uname)
        else:
            username_line = t("stats.user_detail.username_none", locale)
        text = (
            f"{t('stats.user_detail.title', locale)}\n\n"
            f"{t('stats.user_detail.name', locale, user=Safe(user_ref(uid, fname, uname)))}\n"
            f"{t('stats.user_detail.id', locale, id=Safe(code(str(uid))))}\n"
            f"{username_line}\n"
            f"{t('stats.user_detail.last_name', locale, name=str(last_name))}\n\n"
            f"{t('stats.user_detail.first_seen', locale, date=Safe(commit))}\n"
            f"{t('stats.user_detail.last_seen', locale, date=Safe(seen))}\n\n"
            f"{t('stats.user_detail.check_hint', locale, command=Safe(code(f'/check {uid}')))}"
        )
        kb = back_to_module_kb(f"stats_users:{page}", locale)
        return text, kb
