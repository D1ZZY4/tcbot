# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared pagination helpers used by check_flow and stats_flow."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton

from tcbot.utils.i18n import t
from tcbot.utils.time_and_date import fmt_dt


def paginate[T](items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
    """Slice ``items`` for ``page`` (0-based). Returns ``(chunk, total_pages, clamped_page)``."""
    total = len(items)
    if total == 0 or page_size <= 0:
        return [], 1, 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    return items[start : start + page_size], total_pages, page


def nav_row(
    page: int,
    total_pages: int,
    cb_prefix: str,
    locale: str | None = None,
) -> list[InlineKeyboardButton]:
    """Build a prev/next navigation row when there is more than one page.

    Labels render from the shared button catalog so paged lists follow
    the viewer's locale like every other keyboard.
    """
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(
            InlineKeyboardButton(
                t("button.prev", locale, plain=True),
                callback_data=f"{cb_prefix}:{page - 1}",
            )
        )
    if page < total_pages - 1:
        row.append(
            InlineKeyboardButton(
                t("button.next", locale, plain=True),
                callback_data=f"{cb_prefix}:{page + 1}",
            )
        )
    return row


def date_or_unknown(value: Any, locale: str | None = None) -> str:
    """Format a datetime field or a localized Unknown fallback if missing."""
    return (
        fmt_dt(value) if value else t("common.action.unknown_date", locale, plain=True)
    )
