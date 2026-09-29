# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Paginated /check warn, kick, and mute drill-downs plus their renderer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.keyboards import (
    check_warn_groups_kb,
    check_warns_back_row,
)

# * Name lookups resolve through the package namespace, keeping one live
# * binding for every caller (mirrors ban_flow's _flow pattern).
from tcbot.modules.helper.workflows import check_flow as _flow
from tcbot.modules.helper.workflows.check_flow.shared import (
    _PAGE_SIZE,
    _REASON_PREVIEW_LEN,
    _async_const,
    _back_to_check,
    _maybe_caveat,
    log,
)
from tcbot.utils.formatter import bold, italic, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.pagination import date_or_unknown, nav_row

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import InlineKeyboardButton


class CheckEventsMixin:
    """Warn, kick, and mute drill-down builders for the /check command."""

    @classmethod
    async def warns_by_group(
        cls,
        target_id: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """List groups where the user has warnings + count per group + drill-in buttons."""
        groups, display_name = await asyncio.gather(
            db.warns_db.user_warn_groups(target_id),
            _flow._name(target_id),
            return_exceptions=True,
        )
        if isinstance(groups, BaseException):
            # * Transient DB failure: a retry card, never the empty card. An
            # * outage is not evidence the user is clean.
            text = t("checking.warns.db_fail", locale)
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        if not groups:
            text = t(
                "checking.warns.empty",
                locale,
                user=Safe(user_ref(target_id, display_name)),
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

        try:
            titles = await db.groups_db.get_group_titles([cid for cid, _ in groups])
        except Exception:
            # * Degrade to numeric chat IDs on a transient failure; the empty
            # * row list still renders, mirroring warns_in_group's {} fallback.
            titles = {}
        total = sum(c for _, c in groups)

        lines = [
            t(
                "checking.warns.header",
                locale,
                n=total,
                groups=len(groups),
            )
            + "\n"
        ]
        warn_groups: list[tuple[str, int, int]] = []
        for cid, count in groups:
            title = titles.get(cid) or str(cid)
            lines.append(
                t(
                    "checking.warns.group_line",
                    locale,
                    title=title,
                    n=Safe(bold(str(count))),
                )
            )
            warn_groups.append((title, count, cid))

        return "\n".join(lines), check_warn_groups_kb(
            target_id, warn_groups, locale=locale
        )

    @classmethod
    async def warns_in_group(
        cls,
        target_id: int,
        chat_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of individual warnings inside one chat."""
        count, titles = await asyncio.gather(
            db.warns_db.warn_count(target_id, chat_id),
            db.groups_db.get_group_titles([chat_id]),
            return_exceptions=True,
        )
        if isinstance(titles, BaseException):
            titles = {}
        if isinstance(count, BaseException) or not isinstance(count, int):
            count = 0
            count_failed = True
        else:
            count_failed = False
        total_pages = max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        try:
            warns = await db.warns_db.get_warns(
                target_id,
                chat_id,
                skip=page * _PAGE_SIZE,
                limit=_PAGE_SIZE,
                newest_first=True,
            )
            warns_failed = False
        except Exception:
            log.exception(
                "check_flow warns_in_group fetch failed for %d/%d", target_id, chat_id
            )
            warns = []
            warns_failed = True
        if count_failed:
            # * Honest fallback when the count itself fails: show the fetched page.
            count = len(warns)
            total_pages = max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        # * get_warns already returns newest-first for this view.
        title = titles.get(chat_id) or str(chat_id)

        if not warns:
            text = t("checking.warns.in_empty", locale, title=title)
            rows = [check_warns_back_row(target_id, locale)]
            return _maybe_caveat(
                text, locale, failed=count_failed or warns_failed
            ), InlineKeyboardMarkup(rows)

        # * Resolve admin names with batch query
        admin_ids = [w.get("admin_id", 0) for w in warns if w.get("admin_id")]
        admin_name_map = (
            await db.users_cache.get_first_names_batch(admin_ids) if admin_ids else {}
        )

        lines = [
            t(
                "checking.warns.in_header",
                locale,
                title=title,
                n=count,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, w in enumerate(warns, start=1):
            ts = date_or_unknown(w.get("timestamp"), locale)
            stored_reason = w.get("reason", None)
            reason_short = str(
                stored_reason
                if stored_reason is not None
                else t("checking.events.no_reason", locale, plain=True)
            )[:_REASON_PREVIEW_LEN]
            admin_id = w.get("admin_id", 0)
            admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
            lines.append(
                t(
                    "checking.warns.in_item",
                    locale,
                    i=base_idx + i,
                    ts=Safe(ts),
                    reason=Safe(italic(reason_short)),
                    admin=Safe(user_ref(admin_id, admin_name)),
                )
            )

        rows = []
        nav = nav_row(
            page, total_pages, f"check_warn_chat:{target_id}:{chat_id}", locale
        )
        if nav:
            rows.append(nav)
        rows.append(check_warns_back_row(target_id, locale))
        return _maybe_caveat(
            "\n".join(lines), locale, failed=count_failed
        ), InlineKeyboardMarkup(rows)

    @classmethod
    async def kicks_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every kick record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Kicks",
            db_call=db.kicks_db.user_kicks,
            count_call=db.kicks_db.user_kick_count,
            cb_prefix=f"check_kicks:{target_id}",
            locale=locale,
        )

    @classmethod
    async def mutes_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every mute record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Mutes",
            db_call=db.mutes_db.user_mutes,
            count_call=db.mutes_db.user_mute_count,
            cb_prefix=f"check_mutes:{target_id}",
            locale=locale,
        )


async def _per_chat_event_list(
    target_id: int,
    page: int,
    *,
    heading_name: str,
    db_call: Callable[..., Awaitable[list[Any]]],
    count_call: Callable[[int], Awaitable[int]],
    cb_prefix: str,
    locale: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared renderer for kicks/mutes; both have the same shape.

    Fetches only ``_PAGE_SIZE`` rows plus the real total per page turn,
    so the header stays exact and only the visible slice travels.
    """
    total, display_name = await asyncio.gather(
        count_call(target_id),
        _flow._name(target_id),
        return_exceptions=True,
    )
    if isinstance(display_name, BaseException):
        display_name = str(target_id)
    if isinstance(total, BaseException) or not isinstance(total, int):
        total = 0
        count_failed = True
    else:
        count_failed = False
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    try:
        records = await db_call(target_id, skip=page * _PAGE_SIZE, limit=_PAGE_SIZE)
        records_failed = False
    except Exception:
        log.exception("check_flow %s list fetch failed for %d", cb_prefix, target_id)
        records = []
        records_failed = True
    if count_failed:
        # * Honest fallback when the count itself fails: show the fetched page.
        total = len(records)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    if not records:
        if count_failed or records_failed:
            text = t("checking.warns.db_fail", locale)
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])
        text = t(
            "checking.events.empty",
            locale,
            heading=Safe(bold(heading_name)),
            lower=heading_name.lower(),
            user=Safe(user_ref(target_id, display_name)),
        )
        return _maybe_caveat(text, locale, failed=count_failed), InlineKeyboardMarkup(
            [_back_to_check(target_id, locale)]
        )

    chat_ids = list({r["chat_id"] for r in records if "chat_id" in r})
    admin_ids = [r.get("admin_id", 0) for r in records if r.get("admin_id")]

    # * Resolve all titles + all admin names in parallel with batch query
    titles, admin_name_map = await asyncio.gather(
        db.groups_db.get_group_titles(chat_ids),
        db.users_cache.get_first_names_batch(admin_ids)
        if admin_ids
        else _async_const({}),
        return_exceptions=True,
    )
    if isinstance(titles, BaseException):
        titles = {}
    if isinstance(admin_name_map, BaseException):
        admin_name_map = {}

    lines = [
        t(
            "checking.events.header",
            locale,
            heading=Safe(bold(heading_name)),
            n=total,
            page=page + 1,
            pages=total_pages,
        )
        + "\n"
    ]
    base_idx = page * _PAGE_SIZE
    for i, rec in enumerate(records, start=1):
        ts = date_or_unknown(rec.get("timestamp"), locale)
        stored_reason = rec.get("reason", None)
        reason_short = str(
            stored_reason
            if stored_reason is not None
            else t("checking.events.no_reason", locale, plain=True)
        )[:_REASON_PREVIEW_LEN]
        chat_id = rec.get("chat_id", 0)
        title = titles.get(chat_id) or str(chat_id)
        admin_id = rec.get("admin_id", 0)
        admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
        lines.append(
            t(
                "checking.events.item",
                locale,
                i=base_idx + i,
                ts=Safe(ts),
                title=title,
                reason=Safe(italic(reason_short)),
                admin=Safe(user_ref(admin_id, admin_name)),
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix, locale)
    if nav:
        rows.append(nav)
    rows.append(_back_to_check(target_id, locale))
    return _maybe_caveat(
        "\n".join(lines), locale, failed=count_failed
    ), InlineKeyboardMarkup(rows)
