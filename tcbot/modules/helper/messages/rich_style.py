# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline rich text styles: bold, italic, underline, strike, spoiler.

Only these five inline styles live here. Code and preformatted blocks are in
``rich_format``; links and mentions are in ``rich_link``.
"""

from __future__ import annotations

import html

_HTML_ESCAPE = html.escape


def esc(text: object) -> str:
    """Escape untrusted text for a rich HTML field."""
    return _HTML_ESCAPE(str(text), quote=True)


def bold(text: object) -> str:
    """Render text in rich bold markup."""
    content = esc(text)
    return f"<b>{content}</b>" if content else ""


def italic(text: object) -> str:
    """Render text in rich italic markup."""
    content = esc(text)
    return f"<i>{content}</i>" if content else ""


def underline(text: object) -> str:
    """Render text in rich underline markup."""
    content = esc(text)
    return f"<u>{content}</u>" if content else ""


def strike(text: object) -> str:
    """Render text in rich strikethrough markup."""
    content = esc(text)
    return f"<s>{content}</s>" if content else ""


def spoiler(text: object) -> str:
    """Render text in rich spoiler markup."""
    content = esc(text)
    return f"<tg-spoiler>{content}</tg-spoiler>" if content else ""


__all__ = ["bold", "esc", "italic", "spoiler", "strike", "underline"]
