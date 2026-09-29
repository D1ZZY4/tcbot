# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Start menu, community links, and group-list keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot import cfg
from tcbot.modules.helper.keyboards.common import _https_url
from tcbot.utils.i18n import t


def main_menu_kb(locale: str | None = None) -> InlineKeyboardMarkup:
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


def group_start_kb(
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


def back_to_start_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the start menu."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="back_to_start",
                ),
            ]
        ]
    )


def additional_menu_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Community links menu; rows without a configured URL are omitted."""
    rows: list[list[InlineKeyboardButton]] = []

    channel_url = _https_url(cfg.community_channel_url, "channel")
    group_url = _https_url(cfg.community_group_url, "group")
    channel_btn = (
        InlineKeyboardButton(
            t("button.main_channel", locale, plain=True),
            url=channel_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if channel_url
        else None
    )
    group_btn = (
        InlineKeyboardButton(
            t("button.discussion_group", locale, plain=True),
            url=group_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if group_url
        else None
    )
    if channel_btn or group_btn:
        rows.append([b for b in (channel_btn, group_btn) if b is not None])

    logs_url = _https_url(cfg.community_logs_url, "logs")
    exec_url = _https_url(cfg.community_exec_url, "exec")
    logs_btn = (
        InlineKeyboardButton(
            t("button.logs_channel", locale, plain=True),
            url=logs_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if logs_url
        else None
    )
    exec_btn = (
        InlineKeyboardButton(
            t("button.exec_group", locale, plain=True),
            url=exec_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if exec_url
        else None
    )
    if logs_btn or exec_btn:
        rows.append([b for b in (logs_btn, exec_btn) if b is not None])

    travel_url = _https_url(cfg.community_travel_url, "travel")
    if travel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.travel", locale, plain=True),
                    url=travel_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="back_to_start"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def groups_menu_kb(
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


def tcgroups_kb(*, detailed: bool, locale: str | None = None) -> InlineKeyboardMarkup:
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
