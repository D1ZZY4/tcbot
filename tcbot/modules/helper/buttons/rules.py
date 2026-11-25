# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Keyboards for the rules editor, read menu, and acknowledgement."""

from __future__ import annotations

from typing import Any

from pyrogram.enums import ButtonStyle as KeyboardButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tcbot.modules.helper.buttons.common import back_close_row, close_btn
from tcbot.modules.helper.messages.rules import category_label
from tcbot.utils.i18n import available_locales, display_name, t

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


def editor_panel_btn(
    locale: str | None = None,
    *,
    has_content: bool = False,
) -> InlineKeyboardMarkup:
    """Build the main editor panel.

    The main panel is the root of the editor, so it offers Close but no Back.
    Publishing and Discard only appear once the draft has content: an empty
    draft should guide the reader into the editor, not offer to destroy or
    publish nothing.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(t("button.edit_draft", locale, plain=True), "rules_edit_draft"),
            _button(t("button.preview", locale, plain=True), "rules_preview"),
        ]
    ]
    if has_content:
        rows.append(
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
            ]
        )
    rows.append([_button(t("button.upload_md", locale, plain=True), "rules_upload")])
    rows.append([_button(t("button.rules_language", locale, plain=True), "rules_lang")])
    rows.append([close_btn(locale)])
    return InlineKeyboardMarkup(rows)


def rules_language_btn(current: str, locale: str | None = None) -> InlineKeyboardMarkup:
    """Pick the content language from the locales that have a catalog."""
    rows: list[list[InlineKeyboardButton]] = []
    for code in available_locales():
        label = display_name(code, None) or code
        mark = "✓ " if code == current else ""
        rows.append([_button(f"{mark}{label}", f"rules_lang_set:{code}")])
    rows.append([_button(t("button.next", locale, plain=True), "rules_panel")])
    return InlineKeyboardMarkup(rows)


def preview_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to the editor panel and Close, for the draft preview."""
    return InlineKeyboardMarkup([back_close_row("rules_panel", locale)])


def categories_btn(
    categories: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the category list with add and back actions."""
    rows: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        key = str(cat["category_key"])
        label = category_label(key, locale, str(cat["title"]))
        rows.append([_button(label, f"rules_cat:{key}")])
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


_RULES_PER_PAGE: int = 8


def _nav_rows(
    index: int, total: int, callback: str, locale: str | None
) -> list[list[InlineKeyboardButton]]:
    """Navigation and Close as separate rows, never sharing a line."""
    navigation: list[InlineKeyboardButton] = []
    if index > 0:
        navigation.append(
            _button(
                t("button.prev", locale, plain=True),
                f"{callback}:{index - 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    if index + 1 < total:
        navigation.append(
            _button(
                t("button.next", locale, plain=True),
                f"{callback}:{index + 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    return [navigation, [close_btn(locale)]]


def rules_index_btn(
    categories: list[dict[str, Any]], locale: str | None = None, *, page: int = 0
) -> InlineKeyboardMarkup:
    """Topic buttons, two per row, with Prev/Next/Close for long rule sets."""
    total_pages = max(1, (len(categories) + _RULES_PER_PAGE - 1) // _RULES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = categories[page * _RULES_PER_PAGE : (page + 1) * _RULES_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(
                str(cat.get("label") or cat.get("title") or cat["category_key"]),
                f"rules_show:{cat['category_key']}",
            )
            for cat in chunk[offset : offset + 2]
        ]
        for offset in range(0, len(chunk), 2)
    ]
    rows.extend(_nav_rows(page, total_pages, "rules_index", locale))
    return InlineKeyboardMarkup(rows)


def category_sections_btn(
    sections: list[str], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Section buttons for one category, with Back to the index and Close.

    A category page shows only its own sections. Topic paging belongs to the
    index, so Prev and Next are deliberately absent here.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(label, f"rules_section:{section_index}")
            for section_index, label in enumerate(
                sections[start : start + 2], start=start
            )
        ]
        for start in range(0, len(sections), 2)
    ]
    rows.append(
        [
            _button(
                t("button.back", locale, plain=True),
                "rules_index:0",
                style=KeyboardButtonStyle.SUCCESS,
            )
        ]
    )
    rows.append([close_btn(locale)])
    return InlineKeyboardMarkup(rows)


def rules_section_btn(key: str, locale: str | None = None) -> InlineKeyboardMarkup:
    """Leave one section with Back to its category and Close, and nothing else.

    A section page is a reading view, not a second topic menu: keeping the
    category's section buttons there invites a tap that never changes the
    page.
    """
    return InlineKeyboardMarkup([back_close_row(f"rules_show:{key}", locale)])


def editor_sections_btn(
    items: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """List the draft sections directly; each tap opens one section editor."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(
                str(item.get("title") or f"Section {item['id']}")
                .split(":", 1)[-1]
                .strip(),
                f"rules_section_edit:{item['id']}",
            )
        ]
        for item in items
    ]
    rows.append(
        [
            _button(t("button.add_item", locale, plain=True), "rules_item_add"),
            _button(t("button.upload_md", locale, plain=True), "rules_upload"),
        ]
    )
    rows.append([_button(t("button.preview", locale, plain=True), "rules_preview")])
    # * The live editor reaches its sections through this builder, so the
    # * publish/discard controls must live here too. Gating on content matches
    # * the main editor panel: an empty draft cannot be published or discarded.
    if items:
        rows.append(
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
            ]
        )
    rows.append(
        [
            _button(t("button.back", locale, plain=True), "rules_lang"),
            close_btn(locale),
        ]
    )
    return InlineKeyboardMarkup(rows)


def section_editor_btn(locale: str | None = None) -> InlineKeyboardMarkup:
    """Build the formatting toolbar for one section body."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(t("button.fmt_bold", locale, plain=True), "rules_fmt:bold"),
            _button(t("button.fmt_italic", locale, plain=True), "rules_fmt:italic"),
        ],
        [
            _button(t("button.fmt_list", locale, plain=True), "rules_fmt:list"),
            _button(t("button.fmt_divider", locale, plain=True), "rules_fmt:divider"),
        ],
        [
            _button(t("button.fmt_code", locale, plain=True), "rules_fmt:code"),
            _button(t("button.fmt_plain", locale, plain=True), "rules_fmt:plain"),
        ],
        [
            _button(t("button.rename", locale, plain=True), "rules_section_title"),
        ],
        [
            _button(t("button.back", locale, plain=True), "rules_sections"),
            close_btn(locale),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def draft_preview_btn(
    categories: list[dict[str, Any]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Preview index from draft categories, with Back to the editor."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(
                str(cat.get("title") or cat.get("category_key")),
                f"rules_preview_cat:{cat['category_key']}",
            )
            for cat in categories[offset : offset + 2]
        ]
        for offset in range(0, len(categories), 2)
    ]
    rows.append(
        [
            _button(t("button.back", locale, plain=True), "rules_panel"),
            close_btn(locale),
        ]
    )
    return InlineKeyboardMarkup(rows)


def draft_preview_sections_btn(
    sections: list[str], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Section buttons inside a previewed category, with Back to preview."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            _button(label, f"rules_preview_sec:{index}")
            for index, label in enumerate(sections[start : start + 2], start=start)
        ]
        for start in range(0, len(sections), 2)
    ]
    rows.append(
        [
            _button(t("button.back", locale, plain=True), "rules_preview"),
            close_btn(locale),
        ]
    )
    return InlineKeyboardMarkup(rows)


def editor_items_page_btn(
    index: int, total: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Page controls for the editor item list."""
    return InlineKeyboardMarkup(_nav_rows(index, total, "rules_items_page", locale))


def editor_preview_page_btn(
    index: int, total: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Page controls for the draft preview."""
    return InlineKeyboardMarkup(_nav_rows(index, total, "rules_preview_page", locale))


def rules_page_btn(
    index: int, total: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Navigate topic pages with a Prev/Next row and a separate Close row."""
    navigation: list[InlineKeyboardButton] = []
    if index > 0:
        navigation.append(
            _button(
                t("button.prev", locale, plain=True),
                f"rules_prev:{index - 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    if index + 1 < total:
        navigation.append(
            _button(
                t("button.next", locale, plain=True),
                f"rules_next:{index + 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    return InlineKeyboardMarkup([navigation, [close_btn(locale)]])


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
