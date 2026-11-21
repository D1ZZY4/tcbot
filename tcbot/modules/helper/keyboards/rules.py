# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Keyboards for the rules editor, read menu, and acknowledgement."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.keyboards.common import back_row
from tcbot.utils.i18n import t


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text, callback_data=data, style=KeyboardButtonStyle.PRIMARY
    )


def editor_panel_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Build the main editor panel with edit, preview, and publish actions."""
    return InlineKeyboardMarkup(
        [
            [
                _button(t("button.edit_draft", locale, plain=True), "rules_edit_draft"),
                _button(t("button.preview", locale, plain=True), "rules_preview"),
            ],
            [
                _button(t("button.publish", locale, plain=True), "rules_publish"),
                _button(t("button.discard", locale, plain=True), "rules_discard"),
            ],
            [_button(t("button.settings", locale, plain=True), "rules_settings")],
        ]
    )


def categories_kb(
    categories: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the category list with add and back actions."""
    rows: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        key = str(cat["category_key"])
        rows.append([_button(str(cat["title"]), f"rules_cat:{key}")])
        rows.append(
            [
                _button(
                    t("button.rename", locale, plain=True), f"rules_cat_rename:{key}"
                ),
                _button(t("button.up", locale, plain=True), f"rules_cat_up:{key}"),
                _button(t("button.down", locale, plain=True), f"rules_cat_down:{key}"),
                _button(t("button.delete", locale, plain=True), f"rules_cat_del:{key}"),
            ]
        )
    rows.append(
        [_button(t("button.add_category", locale, plain=True), "rules_cat_add")]
    )
    rows.append(back_row("rules_panel", locale))
    return InlineKeyboardMarkup(rows)


def items_kb(
    items: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the item list of one category."""
    rows: list[list[InlineKeyboardButton]] = [
        [_button(str(item["title"]), f"rules_item:{int(item['id'])}")] for item in items
    ]
    rows.append([_button(t("button.add_item", locale, plain=True), "rules_item_add")])
    rows.append(back_row("rules_categories", locale))
    return InlineKeyboardMarkup(rows)


def confirm_kb(
    yes_callback: str, no_callback: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build a two-button confirmation for a destructive editor step."""
    return InlineKeyboardMarkup(
        [
            [
                _button(t("button.confirm", locale, plain=True), yes_callback),
                _button(t("button.cancel", locale, plain=True), no_callback),
            ]
        ]
    )


def rules_menu_kb(
    categories: list[dict[str, Any]], locale: str | None = None, *, page: int = 0
) -> InlineKeyboardMarkup:
    """Build a two-per-row category grid with an optional More page."""
    per_page = 8
    chunk = categories[page * per_page : (page + 1) * per_page]
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(str(cat["title"]), f"rules_show:{cat['category_key']}")
            for cat in chunk[index : index + 2]
        ]
        for index in range(0, len(chunk), 2)
    ]
    if (page + 1) * per_page < len(categories):
        rows.append(
            [_button(t("button.more", locale, plain=True), f"rules_page:{page + 1}")]
        )
    return InlineKeyboardMarkup(rows)


def category_back_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Build the Back button from a category view to the rules menu."""
    return InlineKeyboardMarkup([back_row("rules_menu", locale)])


def ack_kb(
    version_id: int, member_id: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the single I agree button attached to a new member's greeting."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.agree", locale, plain=True),
                    callback_data=f"rules_ack:{version_id}:{member_id}",
                    style=KeyboardButtonStyle.SUCCESS,
                )
            ]
        ]
    )
