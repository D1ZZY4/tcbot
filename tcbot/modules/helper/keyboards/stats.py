# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Stats main menu and back-button rows."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.keyboards.common import back_markup, back_row
from tcbot.utils.i18n import t


def stats_back_row(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Single Back button row returning to the stats main menu."""
    return back_row("stats_main", locale)


def stats_main_kb(
    *,
    show_users: bool = False,
    show_staff: bool = False,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Top-level /tcstats menu: Staff / Bans / Chats drill-downs.

    The drill-down panes enumerate federation-wide records, so their
    buttons render for TC Staff only; the ``stats_*`` callbacks enforce
    the same gate, so a stale or crafted tap still cannot open them. The
    Users list exposes every cached user ID and stays Owner/Founder only.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if show_staff:
        rows.append(
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
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    t("stats.button.chats", locale, plain=True),
                    callback_data="stats_chats:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ]
        )
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
    return back_markup("stats_main", locale)
