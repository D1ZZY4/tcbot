# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Keyboards for the rules editor, read menu, and acknowledgement."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.buttons.common import back_close_row
from tcbot.utils.i18n import t

# * Callback payloads of the moderation rules picker, shared by the ban and
# * reason flows. The picker keyboard owns them because it emits them.
PICKER_PICK_PREFIX = "rules_step:pick:"
PICKER_OTHER = "rules_step:other"
PICKER_DONE = "rules_step:done"
PICKER_CLEAR = "rules_step:clear"
PICKER_CANCEL = "rules_step:cancel"


def picker_btn(
    items: list[dict[str, Any]], selected: list[int], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the moderation rules picker with toggles and control buttons."""
    selected_ids = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        item_id = int(item["id"])
        mark = "[x] " if item_id in selected_ids else "[ ] "
        rows.append(
            [
                InlineKeyboardButton(
                    mark + str(item["title"]),
                    callback_data=f"{PICKER_PICK_PREFIX}{item_id}",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("rules.picker.other", locale, plain=True),
                callback_data=PICKER_OTHER,
            ),
            InlineKeyboardButton(
                t("button.done", locale, plain=True),
                callback_data=PICKER_DONE,
                style=KeyboardButtonStyle.SUCCESS,
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                t("rules.picker.clear", locale, plain=True),
                callback_data=PICKER_CLEAR,
            ),
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True),
                callback_data=PICKER_CANCEL,
                style=KeyboardButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _button(
    text: str, data: str, *, style: KeyboardButtonStyle = KeyboardButtonStyle.PRIMARY
) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data, style=style)


def prompt_btn(back_callback: str, locale: str | None = None) -> InlineKeyboardMarkup:
    """Back and Close navigation for a text-entry step of the editor."""
    return InlineKeyboardMarkup([back_close_row(back_callback, locale)])


def editor_panel_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Build the main editor panel with edit, preview, and publish actions."""
    return InlineKeyboardMarkup(
        [
            [
                _button(t("button.edit_draft", locale, plain=True), "rules_edit_draft"),
                _button(t("button.preview", locale, plain=True), "rules_preview"),
            ],
            [
                _button(
                    t("button.publish", locale, plain=True),
                    "rules_publish",
                    style=KeyboardButtonStyle.SUCCESS,
                ),
                _button(
                    t("button.discard", locale, plain=True),
                    "rules_discard",
                    style=KeyboardButtonStyle.DANGER,
                ),
            ],
            [_button(t("button.settings", locale, plain=True), "rules_settings")],
            back_close_row("back_to_start", locale),
        ]
    )


def categories_btn(
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
                _button(
                    t("button.delete", locale, plain=True),
                    f"rules_cat_del:{key}",
                    style=KeyboardButtonStyle.DANGER,
                ),
            ]
        )
    rows.append(
        [_button(t("button.add_category", locale, plain=True), "rules_cat_add")]
    )
    rows.append(back_close_row("rules_panel", locale))
    return InlineKeyboardMarkup(rows)


def items_btn(
    items: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the item list of one category."""
    # * The titles are the list; there is no per-item detail surface, so no
    # * dead rules_item button is emitted here.
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([_button(t("button.add_item", locale, plain=True), "rules_item_add")])
    rows.append(back_close_row("rules_categories", locale))
    return InlineKeyboardMarkup(rows)


def confirm_btn(
    yes_callback: str, no_callback: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build a two-button confirmation for a destructive editor step."""
    return InlineKeyboardMarkup(
        [
            [
                _button(
                    t("button.confirm", locale, plain=True),
                    yes_callback,
                    style=KeyboardButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data=no_callback,
                    style=KeyboardButtonStyle.DANGER,
                ),
            ],
            back_close_row("rules_panel", locale),
        ]
    )


def rules_menu_btn(
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
    rows.append(back_close_row("back_to_start", locale))
    return InlineKeyboardMarkup(rows)


def category_back_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to the rules menu and Close, for a category view."""
    return InlineKeyboardMarkup([back_close_row("rules_menu", locale)])


def ack_btn(
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
