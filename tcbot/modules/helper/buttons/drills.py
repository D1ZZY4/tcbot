# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Paginated drill-down lists and stats search buttons."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyrogram.enums import ButtonStyle as KeyboardButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tcbot.modules.helper.buttons.common import back_button
from tcbot.modules.helper.buttons.nav import nav_row
from tcbot.utils.i18n import t

if TYPE_CHECKING:
    from collections.abc import Sequence


def paged_drill_btn(
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
    rows.append([back_button(back_callback, locale)])
    return InlineKeyboardMarkup(rows)


def stats_list_btn(
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

    return paged_drill_btn(
        [(str(i + 1), _callback(i)) for i in range(n_items)],
        page=page,
        total_pages=total_pages,
        nav_prefix=cb_prefix,
        back_callback="stats_main",
        extra_rows=[extra_row] if extra_row is not None else None,
        per_row=3,
        locale=locale,
    )


def stats_list_nav_btn(
    page: int,
    total_pages: int,
    cb_prefix: str,
    *,
    extra_row: list[InlineKeyboardButton] | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Navigation-only keyboard for a table view: Prev/Next, extras, Back.

    Table rows carry their own details, so no numbered drill-in buttons are
    needed. Only the navigation controls remain.
    """
    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix, locale)
    if nav:
        rows.append(nav)
    if extra_row is not None:
        rows.append(list(extra_row))
    rows.append([back_button("stats_main", locale)])
    return InlineKeyboardMarkup(rows)


def stats_search_results_nav_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Search results keyboard: New Search and Back, no numbered rows."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.new_search", locale, plain=True),
                    callback_data="stats_bans_search",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                back_button("stats_search_back", locale),
            ]
        ]
    )


def stats_search_panel_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Search panel keyboard: Cancel only."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data="stats_search_cancel",
                    style=KeyboardButtonStyle.DANGER,
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


def stats_search_results_btn(
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
                style=KeyboardButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)
