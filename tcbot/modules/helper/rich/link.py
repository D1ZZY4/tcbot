# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich links and user mentions.

Buttons live in :mod:`tcbot.modules.helper.rich.button` and are imported
from that source module, never re-exported here.
"""

from __future__ import annotations

from tcbot.modules.helper.rich.style import bold, esc


def link(text: object, url: str) -> str:
    """Render an inline link, escaping both label and URL."""
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def user_ref(user_id: int, name: str) -> str:
    """Mention a user by ID. Non-positive IDs render as bold text."""
    label = str(name) if name else str(user_id)
    if user_id <= 0:
        return bold(label)
    return link(label, f"tg://user?id={user_id}")


def mention(user_id: int, name: str) -> str:
    """Alias of :func:`user_ref` for call sites that read as a mention."""
    return user_ref(user_id, name)


__all__ = ["link", "mention", "user_ref"]
