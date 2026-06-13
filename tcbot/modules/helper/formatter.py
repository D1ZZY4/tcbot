# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""HTML text formatters: mention(), code(), bold(), and other inline-markup helpers."""

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


def link(text: str, url: str) -> str:
    """Wrap text in an HTML anchor tag pointing to url, escaping the display text."""
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
    """Escape HTML special characters in text for safe inline inclusion in HTML messages."""
    return html.escape(str(text))


def user_ref(user_id: int, name: str, username: str | None = None) -> str:
    """Format a complete user reference for action confirmation messages.

    Produces a clickable link with a separate code-formatted ID when a
    username is available, a plain escaped name followed by the ID when the
    name differs from the numeric ID, or just the code-formatted ID when the
    name is the raw numeric string (avoiding triple-ID display when the
    fallback name equals the user ID).

    Use this helper instead of the ``mention() - code(id)`` inline pattern so
    that every action summary (ban, unban, warn, kick, mute) formats the
    target consistently and without duplication.
    """
    if username:
        return f'<a href="https://t.me/{html.escape(username)}">{html.escape(str(name))}</a> - {code(str(user_id))}'
    if str(name) == str(user_id):
        return code(str(user_id))
    return f"{html.escape(str(name))} - {code(str(user_id))}"


def proof_line(proof_desc: str | None) -> str:
    r"""Return a formatted proof line or an empty string when no proof is given.

    Produces ``\nProof: <desc>`` when *proof_desc* is a non-empty string,
    or ``""`` otherwise.  Callers embed the result directly in HTML reply text,
    so *proof_desc* is HTML-escaped here at the source.
    """
    return f"\nProof: {esc(proof_desc)}" if proof_desc else ""
