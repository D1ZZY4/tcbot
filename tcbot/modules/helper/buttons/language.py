# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Language selection keyboard."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.buttons.common import back_button


def language_list_btn(
    scope: str,
    items: list[tuple[str, str]],
    *,
    back_label: str | None = None,
    back_callback: str | None = None,
    selected: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """One button per locale plus an optional Back row.

    Each button sends ``lang:set:<scope>:<locale>``; the current setting
    gets a checkmark text prefix (a plain character, not emoji). The Back row sends the given
    callback verbatim, so the start-menu path returns to ``back_to_start``
    while the command path omits it.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"✓ {name}" if code == selected else name,
                callback_data=f"lang:set:{scope}:{code}",
                style=(
                    KeyboardButtonStyle.SUCCESS
                    if code == selected
                    else KeyboardButtonStyle.PRIMARY
                ),
            )
        ]
        for name, code in items
    ]
    if back_callback is not None:
        # * The label comes from the shared Back button so its style and
        # * wording cannot drift; back_label stays for older callers.
        _ = back_label
        rows.append([back_button(back_callback, locale)])
    return InlineKeyboardMarkup(rows)
