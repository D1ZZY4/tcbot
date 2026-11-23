# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared rules-picker step for moderation flows.

The picker is deliberately independent of a specific moderation action: a
conversation scope stores the selected item ids and an optional note in its conversation
scope, then passes them to the decision writer. When no rules are published
the flow simply skips this step, so moderation never stalls on missing
content.
"""

from __future__ import annotations

from typing import Any

from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.messages.rules import category_label, selected_summary
from tcbot.utils.i18n import t

_PREFIX = rules_btn.PICKER_PICK_PREFIX


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


def picker_text(
    items: list[dict[str, Any]], selected: list[int], locale: str | None = None
) -> str:
    """Build the prompt, highlighting the current selection and its tier."""
    selected_ids = set(selected)
    titles = [
        f"{category_label(str(item.get('category_key') or ''), locale, str(item.get('category_title') or 'Rules'))}: "
        f"{item['title']}"
        for item in items
        if int(item["id"]) in selected_ids
    ]
    chosen = selected_summary(titles, None, locale)
    return f"{t('rules.picker.prompt', locale)}\n\n{chosen}"
