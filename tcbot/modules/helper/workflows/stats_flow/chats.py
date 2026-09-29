# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Connected group list and detail views."""

from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.keyboards import back_to_module_kb
from tcbot.modules.helper.workflows.stats_flow.shared import (
    _PAGE_SIZE,
    _list_kb,
    back_kb,
    launch_group_title_refresh,
)
from tcbot.utils.formatter import bold, code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import date_or_unknown, paginate

log = get_logger(__name__)


class ChatViews:
    """Paginated connected-group roster and single-group detail cards."""

    @classmethod
    async def chats_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active connected group."""
        try:
            groups = await db.groups_db.active_groups()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats chats_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)
        chunk, total_pages, page = paginate(groups, page, _PAGE_SIZE)

        if not groups:
            return t("stats.chats.empty", locale), back_kb(locale)

        lines = [
            t(
                "stats.chats.header",
                locale,
                n=len(groups),
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, grp in enumerate(chunk, start=1):
            lines.append(
                t(
                    "stats.chats.item",
                    locale,
                    i=base_idx + i,
                    title=grp.get("title", "Unknown"),
                    id=Safe(code(str(grp.get("chat_id", 0)))),
                )
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_chats",
            item_cb_prefix="stats_chat_item",
            item_ids=[str(grp.get("chat_id", 0)) for grp in chunk],
            locale=locale,
        )

    @classmethod
    async def chat_detail(
        cls,
        bot: Bot,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a connected group."""
        groups = await db.groups_db.active_groups()
        chunk, _total, page = paginate(groups, page, _PAGE_SIZE)
        if idx < 0 or idx >= len(chunk):
            text = t("stats.error.group_not_found", locale)
            kb = back_to_module_kb(f"stats_chats:{page}", locale)
            return text, kb

        grp = chunk[idx]
        chat_id = grp.get("chat_id", 0)
        if stable is not None and str(chat_id) != stable:
            text = t("stats.error.group_not_found", locale)
            kb = back_to_module_kb(f"stats_chats:{page}", locale)
            return text, kb
        title = grp.get("title", "Unknown")
        # * Stale-while-revalidate: render instantly, persist renames behind.
        launch_group_title_refresh(bot, chat_id)
        added_by = grp.get("added_by", 0)
        adder_fname, adder_uname = await db.users_cache.get_user_mention_data(added_by)
        date_str = date_or_unknown(grp.get("added_date"), locale)

        text = (
            f"{t('stats.chat_detail.title', locale)}\n\n"
            f"{t('stats.chat_detail.name', locale, name=Safe(bold(title)))}\n"
            f"{t('stats.chat_detail.chat_id', locale, id=Safe(code(str(chat_id))))}\n\n"
            f"{t('stats.chat_detail.connected_by', locale, user=Safe(user_ref(added_by, adder_fname, adder_uname)))}\n"
            f"{t('stats.chat_detail.date', locale, date=Safe(date_str))}"
        )
        kb = back_to_module_kb(f"stats_chats:{page}", locale)
        return text, kb
