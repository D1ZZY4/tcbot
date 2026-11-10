# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Page arithmetic shared by the check and statistics views.

Pure list maths only: no Telegram types and no localisation, so the
helpers stay usable by any view that pages a list or a row count.
"""

from __future__ import annotations


def clamp_page(total: int, page: int, page_size: int) -> tuple[int, int]:
    """Return ``(total_pages, clamped_page)`` for a total row count.

    Single owner for the page arithmetic. Views that page a database query
    instead of an in-memory list cannot use :func:`paginate`, but they must
    clamp the same way or a stale page number would read past the end.
    """
    if total <= 0 or page_size <= 0:
        return 1, 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    return total_pages, max(0, min(page, total_pages - 1))


def paginate[T](items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
    """Slice ``items`` for ``page`` (0-based). Returns ``(chunk, total_pages, clamped_page)``."""
    total = len(items)
    total_pages, page = clamp_page(total, page, page_size)
    if total == 0 or page_size <= 0:
        return [], total_pages, page
    start = page * page_size
    return items[start : start + page_size], total_pages, page
