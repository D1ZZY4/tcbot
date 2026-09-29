# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Stats main menu and back-button rows."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t


def stats_back_row(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Single Back button row returning to the stats main menu."""
    return [
        InlineKeyboardButton(
            t("button.back", locale, plain=True), callback_data="stats_main"
        )
    ]


def stats_main_kb(
    *, show_users: bool = False, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Top-level /tcstats menu: Staff / Bans / Chats drill-downs.

    The Users list exposes every cached user ID, so its button shows for
    the Owner/Founder only; the stats_users callbacks enforce the same
    gate, so a stale or crafted tap still cannot open the list.
    """
    rows = [
        [
            InlineKeyboardButton(
                t("stats.button.roster", locale, plain=True),
                callback_data="stats_admins",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                t("stats.button.bans", locale, plain=True),
                callback_data="stats_bans:0",
                style=KeyboardButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                t("stats.button.chats", locale, plain=True),
                callback_data="stats_chats:0",
                style=KeyboardButtonStyle.PRIMARY,
            ),
        ],
    ]
    if show_users:
        rows.append(
            [
                InlineKeyboardButton(
                    t("stats.button.users", locale, plain=True),
                    callback_data="stats_users:0",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def stats_back_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the stats main menu."""
    return InlineKeyboardMarkup([stats_back_row(locale)])
