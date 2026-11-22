# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared paginated drill-down keyboard: grid, nav, extras, back."""

from __future__ import annotations

from telegram import InlineKeyboardButton
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.buttons import paged_drill_btn, stats_list_btn


def _texts(markup) -> list[list[str]]:  # type: ignore[no-untyped-def]
    """Extract button labels per row for layout assertions."""
    return [[b.text for b in row] for row in markup.inline_keyboard]


def _styles(markup) -> list[list[object]]:  # type: ignore[no-untyped-def]
    """Extract button styles per row for color assertions."""
    return [[b.to_dict().get("style") for b in row] for row in markup.inline_keyboard]


def test_grid_chunks_three_per_row_with_nav_and_back() -> None:
    btn = paged_drill_btn(
        [(str(i), f"cb:{i}") for i in range(1, 6)],
        page=0,
        total_pages=3,
        nav_prefix="cb",
        back_callback="main",
    )
    assert _texts(btn) == [["1", "2", "3"], ["4", "5"], ["Next ↦"], ["⤎ Back"]]
    assert _styles(btn)[0] == [KeyboardButtonStyle.PRIMARY] * 3
    assert _styles(btn)[-1] == [KeyboardButtonStyle.SUCCESS]


def test_single_page_omits_nav_row() -> None:
    btn = paged_drill_btn(
        [("1", "cb:0")], page=0, total_pages=1, nav_prefix="cb", back_callback="main"
    )
    assert _texts(btn) == [["1"], ["⤎ Back"]]


def test_extra_rows_land_before_back() -> None:
    extra = [[InlineKeyboardButton("Search", callback_data="search")]]
    btn = paged_drill_btn(
        [],
        page=0,
        total_pages=1,
        nav_prefix="cb",
        back_callback="main",
        extra_rows=extra,
    )
    assert _texts(btn) == [["Search"], ["⤎ Back"]]


def test_stats_list_btn_keeps_shape_and_callbacks() -> None:
    btn = stats_list_btn(
        0, 2, 4, cb_prefix="stats_users", item_cb_prefix="stats_user_item"
    )
    rows = btn.inline_keyboard
    assert [b.callback_data for b in rows[0]] == [
        "stats_user_item:0:0",
        "stats_user_item:0:1",
        "stats_user_item:0:2",
    ]
    assert rows[1][0].callback_data == "stats_user_item:0:3"
    assert rows[2][0].callback_data == "stats_users:1"
    assert rows[3][0].callback_data == "stats_main"
    assert all(
        b.to_dict().get("style") == KeyboardButtonStyle.PRIMARY
        for row in rows[:2]
        for b in row
    )
