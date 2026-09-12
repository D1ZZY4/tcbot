# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MarkdownV2 text formatters: the single source of truth for all Telegram markup.

All modules (including tcbot.utils) import from here. Every message is
sent with ``parse_mode="MarkdownV2"``; these helpers own both the entity
markers and the escaping so callers never hand-roll either.

Escaping contract (per the Bot API MarkdownV2 spec, verified against the
official docs): ``_*[]()~`>#+-=|{}.!`` must be backslash-escaped in
regular text. Inside ``pre``/``code`` spans only backticks and
backslashes are escaped. Inside link URLs only closing parens and
backslashes are escaped.
"""

from __future__ import annotations

import re

# * Telegram usernames are restricted to ASCII letters, digits, and
# * underscores (5-32 chars). Anything else in a cached username means the
# * value did not come from Telegram intact, so never put it into a URL.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")

# * Full MarkdownV2 special set for regular text (19 chars per the Bot API
# * spec: the 18 punctuation marks plus the backslash itself, which must
# * be escaped everywhere outside pre/code spans). Built once so the hot
# * path below is a single str.translate over a precomputed table.
_MD_V2_TEXT_SPECIAL: str = "_*[]()~`>#+-=|{}.!\\"
_MD_V2_TEXT_ESCAPE_TABLE: dict[int, str] = {
    ord(c): f"\\{c}" for c in _MD_V2_TEXT_SPECIAL
}

# * Inside pre/code spans only these two can break parsing.
_MD_V2_CODE_ESCAPE_TABLE: dict[int, str] = {ord(c): f"\\{c}" for c in ("`", "\\")}

# * Inside (url) only these two can break parsing.
_MD_V2_URL_ESCAPE_TABLE: dict[int, str] = {ord(c): f"\\{c}" for c in (")", "\\")}


def safe_username(username: str | None) -> str | None:
    """Return ``username`` only when it is a valid Telegram username shape."""
    if username and _USERNAME_RE.match(username):
        return username
    return None


def esc(text: str) -> str:
    """Escape text for safe inline inclusion in MarkdownV2 messages."""
    return str(text).translate(_MD_V2_TEXT_ESCAPE_TABLE)


def bold(text: str) -> str:
    """Wrap text in MarkdownV2 bold markers, escaping the content first.

    Empty input renders as an empty string: bare ``**`` would fail entity
    parsing and drop the whole message.
    """
    content = esc(text)
    return f"*{content}*" if content else ""


def italic(text: str) -> str:
    """Wrap text in MarkdownV2 italic markers, escaping the content first.

    Empty input renders as an empty string, like :func:`bold`.
    """
    content = esc(text)
    return f"_{content}_" if content else ""


def code(text: str) -> str:
    """Wrap text in a MarkdownV2 code span, escaping backticks and backslashes.

    Other special characters stay literal inside code spans per the spec,
    so IDs and timestamps render cleanly without backslash noise. Empty
    input renders as an empty string.
    """
    content = str(text).translate(_MD_V2_CODE_ESCAPE_TABLE)
    return f"`{content}`" if content else ""


def pre(text: str) -> str:
    """Wrap text in a MarkdownV2 pre block, escaping backticks and backslashes."""
    content = str(text).translate(_MD_V2_CODE_ESCAPE_TABLE)
    return f"```{content}```" if content else ""


def link(text: str, url: str) -> str:
    """Build a MarkdownV2 ``[text](url)`` link, escaping both parts."""
    return f"[{esc(text)}]({str(url).translate(_MD_V2_URL_ESCAPE_TABLE)})"


def mention(user_id: int, name: str, username: str | None = None) -> str:
    """Create a user mention with username link and always-included user ID link.

    Historical alias for :func:`user_ref`; both names format the same
    output. New code should prefer :func:`user_ref` directly.
    """
    return user_ref(user_id, name, username)


def user_ref(user_id: int, name: str, username: str | None = None) -> str:
    """Format a complete user reference for action confirmation messages.

    Always a clickable ``FullName`` resolving via ``tg://user?id=ID``: the
    numeric ID is the single source of truth for identity. Usernames are
    never used: they can change, be reused, or be missing, while the
    numeric ID always resolves. The ``username`` parameter is accepted for
    backward compatibility and ignored.
    """
    _ = username
    return f"[{esc(str(name))}](tg://user?id={user_id})"
