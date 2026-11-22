# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Previous/next navigation row for paged views."""

from __future__ import annotations

from telegram import InlineKeyboardButton

from tcbot.utils.i18n import t


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
