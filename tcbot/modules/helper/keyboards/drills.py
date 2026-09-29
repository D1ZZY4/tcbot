# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Paginated drill-down lists and stats search keyboards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t
from tcbot.utils.pagination import nav_row

if TYPE_CHECKING:
    from collections.abc import Sequence


def paged_drill_kb(
    items: Sequence[tuple[str, str]],
    *,
    page: int,
    total_pages: int,
    nav_prefix: str,
    back_callback: str,
    extra_rows: Sequence[Sequence[InlineKeyboardButton]] | None = None,
    per_row: int = 3,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Numbered drill-in grid plus nav row, optional extras, and back.

    Single owner for the numbered-grid look (the one place numbered
    buttons gain PRIMARY), shared by the stats and check drill-downs.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                label, callback_data=cb, style=KeyboardButtonStyle.PRIMARY
            )
            for label, cb in items[i : i + per_row]
        ]
        for i in range(0, len(items), per_row)
    ]
    nav = nav_row(page, total_pages, nav_prefix, locale)
    if nav:
        rows.append(nav)
    if extra_rows:
        rows.extend([list(row) for row in extra_rows])
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data=back_callback
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def stats_list_kb(
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
    """Nav plus numbered detail buttons plus optional extra row plus back.

    ``item_ids`` carries one stable entity ID per button so a list
    mutation between render and tap cannot silently show another record.
    Buttons without the segment keep working.
    """

    def _callback(i: int) -> str:
        base = f"{item_cb_prefix}:{page}:{i}"
        if item_ids is not None and i < len(item_ids):
            return f"{base}:{item_ids[i]}"
        return base

    return paged_drill_kb(
        [(str(i + 1), _callback(i)) for i in range(n_items)],
        page=page,
        total_pages=total_pages,
        nav_prefix=cb_prefix,
        back_callback="stats_main",
        extra_rows=[extra_row] if extra_row is not None else None,
        per_row=3,
        locale=locale,
    )


def stats_search_panel_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Search panel keyboard: Cancel only."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data="stats_search_cancel",
                )
            ]
        ]
    )


def stats_search_row(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Single Search button row opening the bans search panel."""
    return [
        InlineKeyboardButton(
            t("button.search", locale, plain=True),
            callback_data="stats_bans_search",
            style=KeyboardButtonStyle.PRIMARY,
        ),
    ]


def stats_search_results_kb(
    n: int, locale: str | None = None, *, item_ids: list[str] | None = None
) -> InlineKeyboardMarkup:
    """Numbered search-result buttons plus New Search / Cancel row.

    ``item_ids`` carries one stable ban ID per button; the detail handler
    verifies it so a list mutation between render and tap cannot silently
    show another ban. Buttons without the segment keep working.
    """
    num_btns = [
        InlineKeyboardButton(
            str(i + 1),
            callback_data=(
                f"stats_search_item:{i}:{item_ids[i]}"
                if item_ids is not None and i < len(item_ids)
                else f"stats_search_item:{i}"
            ),
            style=KeyboardButtonStyle.PRIMARY,
        )
        for i in range(n)
    ]
    rows: list[list[InlineKeyboardButton]] = [
        num_btns[i : i + 3] for i in range(0, len(num_btns), 3)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                t("button.new_search", locale, plain=True),
                callback_data="stats_bans_search",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True),
                callback_data="stats_search_cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)
