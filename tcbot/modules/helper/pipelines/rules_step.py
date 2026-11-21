# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared rules-picker step for moderation flows.

The picker is deliberately independent of a specific moderation action: a
flow stores the selected item ids and an optional note in its conversation
scope, then passes them to the decision writer. When no rules are published
the flow simply skips this step, so moderation never stalls on missing
content.
"""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.messages.rules import selected_summary
from tcbot.utils.i18n import t

_OTHER_CALLBACK = "rules_step:other"
_DONE_CALLBACK = "rules_step:done"
_CLEAR_CALLBACK = "rules_step:clear"
_CANCEL_CALLBACK = "rules_step:cancel"

_PREFIX = "rules_step:pick:"


def callback_for(item_id: int) -> str:
    """Return the callback payload that toggles one rule item."""
    return f"{_PREFIX}{item_id}"


def item_id_from_callback(data: str) -> int | None:
    """Return the item id of a picker toggle, or None for a control button."""
    if not data.startswith(_PREFIX):
        return None
    try:
        return int(data[len(_PREFIX) :])
    except ValueError:
        return None


def toggle(selected: list[int], item_id: int) -> list[int]:
    """Toggle one item id without changing the order of the others."""
    result = [int(value) for value in selected]
    if item_id in result:
        result.remove(item_id)
    else:
        result.append(item_id)
    return result


def picker_markup(
    items: list[dict[str, Any]], selected: list[int], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Build the item grid with toggle, Other, Done, Clear, and Cancel."""
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        item_id = int(item["id"])
        mark = "[x] " if item_id in selected else "[ ] "
        rows.append(
            [
                InlineKeyboardButton(
                    mark + str(item["title"]),
                    callback_data=callback_for(item_id),
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("rules.picker.other", locale, plain=True),
                callback_data=_OTHER_CALLBACK,
            ),
            InlineKeyboardButton(
                t("button.done", locale, plain=True),
                callback_data=_DONE_CALLBACK,
                style=KeyboardButtonStyle.SUCCESS,
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                t("rules.picker.clear", locale, plain=True),
                callback_data=_CLEAR_CALLBACK,
            ),
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True), callback_data=_CANCEL_CALLBACK
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def picker_text(
    items: list[dict[str, Any]], selected: list[int], locale: str | None = None
) -> str:
    """Build the prompt, highlighting the current selection."""
    selected_ids = set(selected)
    titles = [str(item["title"]) for item in items if int(item["id"]) in selected_ids]
    chosen = selected_summary(titles, None, locale)
    return f"{t('rules.picker.prompt', locale)}\n\n{chosen}"


def is_control(data: str) -> bool:
    """Return True for a picker control button rather than an item toggle."""
    return data in {
        _OTHER_CALLBACK,
        _DONE_CALLBACK,
        _CLEAR_CALLBACK,
        _CANCEL_CALLBACK,
    }
