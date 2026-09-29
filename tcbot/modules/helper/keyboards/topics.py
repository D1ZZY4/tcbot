# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help index, module help, and privacy keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.keyboards.common import _build_topic_rows
from tcbot.utils.i18n import t


def help_topics_menu_kb(
    topics: list[tuple[str, str]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Help index from the start menu: topics plus Back to start."""
    rows = _build_topic_rows(topics, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="back_to_start"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def help_topics_kb(topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Help index from /help: topics only, no Back to start."""
    return InlineKeyboardMarkup(
        _build_topic_rows(topics, style=KeyboardButtonStyle.PRIMARY)
    )


def back_to_help_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to the menu-path help index (help_menu)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True), callback_data="help_menu"
                ),
            ]
        ]
    )


def back_to_help_cmd_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to the command-path help index (helpc_main)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True), callback_data="helpc_main"
                ),
            ]
        ]
    )


def module_help_kb(
    section_buttons: list[tuple[str, str]],
    back_callback: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Per-module help view: paired sub-section buttons plus Back last."""
    rows = _build_topic_rows(section_buttons, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data=back_callback
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_module_kb(
    module_callback: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Single Back button returning to the module help view."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data=module_callback,
                )
            ]
        ]
    )


def privacy_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Privacy section: policy link plus Back to start."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.privacy_policy", locale, plain=True),
                    callback_data="privacy_policy_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="back_to_start",
                )
            ],
        ]
    )


def privacy_policy_sections_kb(
    section_labels: list[str], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Policy index: one button per section plus Back to privacy."""
    pairs: list[tuple[str, str]] = [
        (label, f"privacy_section_{idx}") for idx, label in enumerate(section_labels)
    ]
    rows = _build_topic_rows(pairs, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="privacy_menu"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_privacy_policy_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to the privacy policy section index."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="privacy_policy_menu",
                )
            ]
        ]
    )
