# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Start menu, community links, and group-list buttons."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot import cfg
from tcbot.modules.helper.buttons.common import back_markup
from tcbot.modules.helper.messages import links as community_links
from tcbot.utils.i18n import t

if TYPE_CHECKING:
    from telegram import Bot


def main_menu_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Top-level start menu: About, Help, Additional, Privacy, Language."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.about", locale, plain=True),
                    callback_data="about_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t("button.help", locale, plain=True),
                    callback_data="help_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t("button.additional", locale, plain=True),
                    callback_data="additional_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t("button.privacy", locale, plain=True),
                    callback_data="privacy_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t("button.language", locale, plain=True),
                    callback_data="language_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def group_start_btn(
    bot_username: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Group /start keyboard: Open PM link plus group help button."""
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.open_pm", locale, plain=True),
                    url=f"https://t.me/{bot_username}?start=menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("button.help", locale, plain=True),
                callback_data="help_menu_group",
                style=KeyboardButtonStyle.PRIMARY,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_start_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the start menu."""
    return back_markup("back_to_start", locale)


async def additional_menu_btn(
    bot: Bot, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Community links menu; chats without a public link are omitted.

    The four lookups are independent and share no state, so they run in
    parallel. A chat that cannot be resolved simply drops its button.
    """
    rows: list[list[InlineKeyboardButton]] = []
    channel_id, group_id, appeals_id, logs_id = await asyncio.gather(
        community_links.resolve(bot, cfg.main_channel),
        community_links.resolve(bot, cfg.main_group),
        community_links.resolve(bot, cfg.appeals[0]),
        community_links.resolve(bot, cfg.logs[0]),
    )
    channel_btn = (
        InlineKeyboardButton(
            t("button.main_channel", locale, plain=True),
            url=channel_id,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if channel_id
        else None
    )
    group_btn = (
        InlineKeyboardButton(
            t("button.discussion_group", locale, plain=True),
            url=group_id,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if group_id
        else None
    )
    appeal_btn = (
        InlineKeyboardButton(
            t("button.appeals_channel", locale, plain=True),
            url=appeals_id,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if appeals_id
        else None
    )
    first_row = [b for b in (channel_btn, group_btn, appeal_btn) if b is not None]
    if first_row:
        rows.append(first_row)

    logs_btn = (
        InlineKeyboardButton(
            t("button.logs_channel", locale, plain=True),
            url=logs_id,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if logs_id
        else None
    )
    if logs_btn:
        rows.append([logs_btn])

    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="back_to_start"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def groups_menu_btn(
    *, detailed: bool, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Start-menu groups list: Detailed/Simple toggle plus Back."""
    toggle = InlineKeyboardButton(
        t("button.simple", locale, plain=True)
        if detailed
        else t("button.details_toggle", locale, plain=True),
        callback_data="menu_groups_simple" if detailed else "menu_groups_details",
        style=KeyboardButtonStyle.PRIMARY,
    )
    back = InlineKeyboardButton(
        t("button.back", locale, plain=True), callback_data="back_to_start"
    )
    return InlineKeyboardMarkup([[toggle, back]])


def tcgroups_btn(*, detailed: bool, locale: str | None = None) -> InlineKeyboardMarkup:
    """Toggle keyboard for /tcgroups: Simple/Details switch."""
    label = (
        t("button.simple", locale, plain=True)
        if detailed
        else t("button.details_toggle", locale, plain=True)
    )
    callback = "groups_simple" if detailed else "groups_details"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    callback_data=callback,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        ]
    )
