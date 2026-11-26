# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline rich-text styles: escaping, emphasis, spoiler, sub and superscript.

Escaping has one owner: :func:`esc`. Every helper escapes its input first and
returns rich HTML inline markup. Code and preformatted blocks live in
``rich.formats``; links and mentions live in ``rich.link`` and ``rich.button``.
"""

from __future__ import annotations

import html


def esc(text: object) -> str:
    """Escape untrusted text for a rich HTML field."""
    return html.escape(str(text), quote=True)


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


def subscript(text: object) -> str:
    """Render text as rich subscript."""
    content = esc(text)
    return f"<sub>{content}</sub>" if content else ""


def superscript(text: object) -> str:
    """Render text as rich superscript."""
    content = esc(text)
    return f"<sup>{content}</sup>" if content else ""


__all__ = [
    "bold",
    "esc",
    "italic",
    "spoiler",
    "strike",
    "subscript",
    "superscript",
    "underline",
]
