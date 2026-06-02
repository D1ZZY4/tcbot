# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""HTML text formatters: mention(), code(), bold(), and other inline-markup helpers."""

from __future__ import annotations

import html


def bold(text: str) -> str:
    return f"<b>{html.escape(str(text))}</b>"


def italic(text: str) -> str:
    return f"<i>{html.escape(str(text))}</i>"


def code(text: str) -> str:
    return f"<code>{html.escape(str(text))}</code>"


def link(text: str, url: str) -> str:
    return f'<a href="{url}">{html.escape(str(text))}</a>'


def mention(user_id: int, name: str, username: str | None = None) -> str:
    """Create a user mention with username fallback.

    If username is available, creates a global mention link (works everywhere).
    Otherwise, falls back to plain text name with copyable user ID.
    """
    if username:
        return f'<a href="https://t.me/{username}">{html.escape(str(name))}</a>'
    return f"{html.escape(str(name))} <code>{user_id}</code>"


def esc(text: str) -> str:
    return html.escape(str(text))
