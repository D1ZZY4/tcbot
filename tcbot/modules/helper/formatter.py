# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## HTML formatting helpers and shared brand constant
from __future__ import annotations

import html

from tcbot import cfg

## The exact branding line required in every log message
BRAND = cfg.community_name


def bold(text: str) -> str:
    return f"<b>{html.escape(str(text))}</b>"


def italic(text: str) -> str:
    return f"<i>{html.escape(str(text))}</i>"


def code(text: str) -> str:
    return f"<code>{html.escape(str(text))}</code>"


def link(text: str, url: str) -> str:
    return f'<a href="{url}">{html.escape(str(text))}</a>'


def mention(user_id: int, name: str) -> str:
    """Create a tg:// user mention hyperlink."""
    return f'<a href="tg://user?id={user_id}">{html.escape(str(name))}</a>'


def esc(text: str) -> str:
    return html.escape(str(text))
