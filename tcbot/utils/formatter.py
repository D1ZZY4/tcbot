# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""HTML text formatters: the single source of truth for all Telegram HTML markup.

All modules (including tcbot.utils) import from here.  The shim at
tcbot/modules/helper/formatter.py re-exports every name for backward
compatibility with the modules layer import paths.
"""

from __future__ import annotations

import html


def bold(text: str) -> str:
    """Wrap text in HTML bold tags, escaping any HTML special characters."""
    return f"<b>{html.escape(str(text))}</b>"


def italic(text: str) -> str:
    """Wrap text in HTML italic tags, escaping any HTML special characters."""
    return f"<i>{html.escape(str(text))}</i>"


def code(text: str) -> str:
    """Wrap text in HTML code tags, escaping any HTML special characters."""
    return f"<code>{html.escape(str(text))}</code>"


def pre(text: str) -> str:
    """Wrap text in HTML pre (monospace block) tags, escaping HTML special characters."""
    return f"<pre>{html.escape(str(text))}</pre>"


def link(text: str, url: str) -> str:
    """Wrap text in an HTML anchor tag pointing to url, escaping both text and url."""
    return f'<a href="{html.escape(str(url), quote=True)}">{html.escape(str(text))}</a>'


def mention(user_id: int, name: str, username: str | None = None) -> str:
    """Create a user mention with username link and always-included user ID link.

    When a username is available: ``Name | Username (tg://user?id=ID)``.
    When no username: ``Name (tg://user?id=ID)``.
    When the name is the bare numeric ID: just the ``tg://user?id=ID`` link,
    avoiding a redundant display.
    """
    id_link = f'<a href="tg://user?id={user_id}">{user_id}</a>'
    if username:
        return (
            f"{html.escape(str(name))} | "
            f'<a href="https://t.me/{html.escape(str(username))}">'
            f"{html.escape(str(username))}</a> ({id_link})"
        )
    if str(name) == str(user_id):
        return id_link
    return f"{html.escape(str(name))} ({id_link})"


def esc(text: str) -> str:
    """Escape HTML special characters in text for safe inline inclusion in HTML messages."""
    return html.escape(str(text))


def user_ref(user_id: int, name: str, username: str | None = None) -> str:
    """Format a complete user reference for action confirmation messages.

    When a username is available: ``Name | @username (tg://user?id=ID)``.
    When no username: ``Name (tg://user?id=ID)``.
    When the name is the bare numeric ID: just the ``tg://user?id=ID`` link.

    Use this helper instead of the ``mention() - code(id)`` inline pattern so
    that every action summary (ban, unban, warn, kick, mute) formats the
    target consistently and without duplication.
    """
    id_link = f'<a href="tg://user?id={user_id}">{user_id}</a>'
    if username:
        return (
            f"{html.escape(str(name))} | "
            f'<a href="https://t.me/{html.escape(username)}">'
            f"{html.escape(str(username))}</a> ({id_link})"
        )
    if str(name) == str(user_id):
        return id_link
    return f"{html.escape(str(name))} ({id_link})"
