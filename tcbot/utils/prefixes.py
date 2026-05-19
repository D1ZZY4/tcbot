# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Build command filters that match all configured prefixes (/, !, .) and
provide a lightweight dispatcher for alternative-prefix commands.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Callable, Coroutine
from typing import Any

from telegram.ext import filters

log = logging.getLogger(__name__)


# ─────────────────────── Alt-Prefix Registry ────────────────────── #
# * Stores callbacks for non-slash prefixed commands (!cmd, .cmd)
_ALT_RE = re.compile(r"^[.!]([a-z][a-z0-9]*)(?:@\w+)?(?:\s|$)", re.IGNORECASE)

_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}

def register_command(name: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
    """
    Register an async callback for a given command name (case-insensitive)
    * Adds command handler to the alt-prefix registry
    * Name is stored in lowercase to ensure case-insensitive matching
    * Used for commands that start with ! or . instead of /
    """
    _REGISTRY[name.lower()] = callback


async def dispatch_alt_prefix(update: object, context: object) -> None:
    """
    Dispatch an update to a registered alt-prefix command handler
    * Parses message text against _ALT_RE regex to extract command
    * Injects context.args same as Telegram's native command handler
    * Swallows all exceptions (logs as WARNING) to keep bot stable
    * Never crashes the main loop even if command handler fails
    """
    msg = getattr(update, "effective_message", None)
    if not msg:
        return
    text: str | None = getattr(msg, "text", None)
    if not text:
        return

    m = _ALT_RE.match(text)
    if not m:
        return

    cmd = m.group(1).lower()
    callback = _REGISTRY.get(cmd)
    if callback is None:
        return

    parts = text.strip().split(None, 1)
    context.args = parts[1].split() if len(parts) > 1 else []  # * type: ignore[attr-defined]

    try:
        await callback(update, context)
    except Exception as exc:
        log.warning("dispatch_alt_prefix: handler %r raised %s", cmd, exc)


# ──────────────────────── Prefix Resolution ─────────────────────── #
# * Loads and parses command prefixes from environment variables
def _get_prefixes() -> list[str]:
    """
    Parse PREFIXES env var - supports both list format and plain string
    * Reads PREFIXES from environment, defaults to ["/", "!", "."]
    * Handles both list ("['/', '!']") and plain string ("/!." formats
    * Filters out empty prefixes to avoid invalid regex patterns
    """
    raw = os.getenv("PREFIXES", "").strip()
    if not raw:
        return ["/", "!", "."]

    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(p) for p in parsed if p]
    except Exception:
        pass

    return list(raw)


def _get_custom_prefixes() -> list[str]:
    """
    Return configured prefixes excluding native Telegram slash (/)
    * Used for filters that only match non-Telegram-native commands
    * Returns only custom prefixes like !, . etc.
    """
    return [p for p in _get_prefixes() if p != "/"]


# ───────────────────────── Filter Builders ──────────────────────── #
# * Builds regex filters for commands that work with all prefixes
def build_prefixed_filters(command: str) -> filters.BaseFilter:
    """
    Return a filter matching <prefix><command> for all configured prefixes
    * Builds regex that works with every prefix in _get_prefixes()
    * Case-insensitive matching, supports @mention suffixes
    * Creates a single filter that works for /cmd, !cmd, .cmd etc.
    """
    prefixes = _get_prefixes()
    escaped_prefixes = re.escape("".join(set(prefixes)))
    pattern = rf"^[{escaped_prefixes}]{re.escape(command)}(?:@\w+)?(?:\s|$)"
    return filters.Regex(re.compile(pattern, re.IGNORECASE))


# * Pre-computed filter: any text starting with a CUSTOM (non-slash) prefix
# * Matches !, . etc. - does NOT match Telegram-native /commands
# * Used in __main__.py member-cache guard (intentionally excludes /)
ANY_CMD_FILTER: filters.BaseFilter = filters.Regex(
    re.compile(
        rf"^[{re.escape(''.join(set(_get_custom_prefixes())))}][a-zA-Z]",
        re.IGNORECASE,
    )
)

# * Pre-computed filter: any text starting with ANY configured prefix
# * Includes /, !, . - use in ConversationHandler fallbacks to catch all commands
# * Ensures every prefixed command can escape conversation states
ALL_PREFIXES_CMD_FILTER: filters.BaseFilter = filters.Regex(
    re.compile(
        rf"^[{re.escape(''.join(set(_get_prefixes())))}][a-zA-Z]",
        re.IGNORECASE,
    )
)


# ──────────────────────── Argument Parsing ──────────────────────── #

def parse_cmd_args(text: str | None) -> list[str]:
    """
    Extract arguments from a prefixed command message text
    * Mimics PTB's native argument parsing for alt-prefix commands
    * Returns empty list if no text or no arguments provided
    * Splits text into command and args using first whitespace
    """
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
