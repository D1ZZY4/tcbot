# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared private helpers for the keyboards package."""

from __future__ import annotations

from telegram import InlineKeyboardButton
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * Button colors follow docs/reference/keyboard-styles.md: SUCCESS approves,
# * DANGER rejects or confirms destruction, PRIMARY continues a flow. Older
# * clients ignore the style field, so color is purely additive.


def _https_url(url: str, label: str) -> str | None:
    """Return http(s) URLs, else None so the button is omitted.

    Operator env URLs reach the API verbatim; a bad value would fail late
    at Telegram, so reject it here where the misconfiguration gets logged.
    """
    if url and url.startswith(("https://", "http://")):
        return url
    if url:
        log.warning("Ignoring non-http(s) community URL for %s: %s", label, url)
    return None


def _build_topic_rows(
    topics: list[tuple[str, str]],
    *,
    style: KeyboardButtonStyle | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Pair topics into two-column rows, odd leftover on its own row."""
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(topics), 2):
        chunk = topics[i : i + 2]
        rows.append(
            [
                InlineKeyboardButton(text, callback_data=cb, style=style)
                for text, cb in chunk
            ]
        )
    return rows
