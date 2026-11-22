# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared private helpers for the buttons package."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t

# * Button colors are semantic (see docs/reference/buttons.md): PRIMARY (blue)
# * is the default for actions,
# * navigation, and links; SUCCESS (green) commits a positive decision such
# * as approve, agree, Done, or publish; DANGER (red) marks destructive or
# * rejecting actions such as delete, discard, demote, and reject. Back,
# * Cancel, and page navigation stay unstyled so the colored buttons lead.
# * Older clients ignore the style field, so color is purely additive.


def back_button(callback_data: str, locale: str | None = None) -> InlineKeyboardButton:
    """Build the shared Back button, colored green as a positive navigation."""
    return InlineKeyboardButton(
        t("button.back", locale, plain=True),
        callback_data=callback_data,
        style=KeyboardButtonStyle.SUCCESS,
    )


def back_row(
    callback_data: str, locale: str | None = None
) -> list[InlineKeyboardButton]:
    """Single Back button row pointing at ``callback_data``.

    Single owner for the Back button: every view that returns somewhere
    renders the label from the shared button catalog, so the wording,
    callback, and green style stay consistent across the buttons.
    """
    return [back_button(callback_data, locale)]


def close_btn(locale: str | None = None) -> InlineKeyboardButton:
    """Build the Close button that dismisses a read-only panel."""
    return InlineKeyboardButton(
        t("button.close", locale, plain=True),
        callback_data="close_msg",
        style=KeyboardButtonStyle.DANGER,
    )


def back_close_row(
    back_callback: str, locale: str | None = None
) -> list[InlineKeyboardButton]:
    """Back and Close in one row, so every menu offers both exits."""
    return [back_button(back_callback, locale), close_btn(locale)]


def back_markup(callback_data: str, locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to ``callback_data``."""
    return InlineKeyboardMarkup([back_row(callback_data, locale)])


def with_back_row(
    rows: list[list[InlineKeyboardButton]],
    callback_data: str,
    locale: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Append the Back row to ``rows`` and return the new row list."""
    rows.append(back_row(callback_data, locale))
    return rows


def _build_topic_rows(
    topics: list[tuple[str, str]],
    *,
    style: KeyboardButtonStyle | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Pair topics into two-column rows, odd leftover on its own row."""
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(topics), 2):
        chunk = topics[i : i + 2]
        rows.append(
            [
                InlineKeyboardButton(text, callback_data=cb, style=style)
                for text, cb in chunk
            ]
        )
    return rows
