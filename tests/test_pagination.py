# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared pagination slicing and navigation rows."""

from __future__ import annotations

from tcbot.utils.pagination import nav_row, paginate


def test_paginate_slices_and_counts() -> None:
    chunk, total_pages, page = paginate(list(range(10)), 1, 4)
    assert chunk == [4, 5, 6, 7]
    assert total_pages == 3
    assert page == 1


def test_paginate_clamps_out_of_range_page() -> None:
    chunk, total_pages, page = paginate(list(range(3)), 9, 2)
    assert page == total_pages - 1
    assert chunk == [2]


def test_paginate_empty() -> None:
    assert paginate([], 0, 5) == ([], 1, 0)


def test_nav_row_middle_has_both_directions() -> None:
    row = nav_row(1, 3, "cb")
    assert [(b.text, b.callback_data) for b in row] == [
        ("« Prev", "cb:0"),
        ("Next »", "cb:2"),
    ]


def test_nav_row_edges_have_single_direction() -> None:
    assert [b.text for b in nav_row(0, 3, "cb")] == ["Next »"]
    assert [b.text for b in nav_row(2, 3, "cb")] == ["« Prev"]
    assert nav_row(0, 1, "cb") == []
