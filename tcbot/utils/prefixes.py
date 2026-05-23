# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Command filter builder for all configured prefixes (/, !, .) and alt-prefix dispatcher.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from telegram.ext import filters

log = logging.getLogger(__name__)


class _MessageLike(Protocol):
    text: str | None


class _UpdateLike(Protocol):
    effective_message: _MessageLike | None


class _ContextLike(Protocol):
    args: list[str]


# ─────────────────────── Alt-Prefix Registry ────────────────────── #
# * Stores callbacks for non-slash prefixed commands (!cmd, .cmd)

_ALT_RE = re.compile(r"^[.!]([a-z][a-z0-9]*)(?:@\w+)?(?:\s|$)", re.IGNORECASE)

_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}


def register_command(
    name: str, callback: Callable[..., Coroutine[Any, Any, None]]
) -> None:
    """Register an async callback for a given command name (case-insensitive)."""
    _REGISTRY[name.lower()] = callback


async def dispatch_alt_prefix(update: _UpdateLike, context: _ContextLike) -> None:
    """
    Dispatch an update to a registered alt-prefix command handler.

    * Parses message text against _ALT_RE to extract the command name
    * Injects context.args the same way PTB's native handler does
    * Swallows all handler exceptions — never crashes the main loop
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
    context.args = parts[1].split() if len(parts) > 1 else []

    try:
        await callback(update, context)
    except Exception as exc:
        log.warning("dispatch_alt_prefix: handler %r raised %s", cmd, exc)


# ──────────────────────── Prefix Resolution ─────────────────────── #


def _get_prefixes() -> list[str]:
    """
    Parse PREFIXES env var — supports both list format and plain string.

    Defaults to ``["/", "!", "."]`` when the variable is unset or empty.
    """
    raw = os.getenv("PREFIXES", "").strip()
    if not raw:
        return ["/", "!", "."]

    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(p) for p in parsed if p]
    except (ValueError, SyntaxError) as exc:
        log.debug("PREFIXES parse fallback to raw string: %s", exc)

    return list(raw)


def _get_custom_prefixes() -> list[str]:
    """Return configured prefixes excluding the native Telegram slash (/)."""
    return [p for p in _get_prefixes() if p != "/"]


# ───────────────────────── Filter Builders ──────────────────────── #


def build_prefixed_filters(command: str) -> filters.BaseFilter:
    """
    Return a filter matching ``<prefix><command>`` for all configured prefixes.

    * Case-insensitive, supports @mention suffixes
    * Works for /cmd, !cmd, .cmd etc. in a single filter
    """
    prefixes = _get_prefixes()
    escaped_prefixes = re.escape("".join(set(prefixes)))
    pattern = rf"^[{escaped_prefixes}]{re.escape(command)}(?:@\w+)?(?:\s|$)"
    return filters.Regex(re.compile(pattern, re.IGNORECASE))


# * Matches !, . etc. — does NOT match Telegram-native /commands
# * Used in __main__.py member-cache guard (intentionally excludes /)
ANY_CMD_FILTER: filters.BaseFilter = filters.Regex(
    re.compile(
        rf"^[{re.escape(''.join(set(_get_custom_prefixes())))}][a-zA-Z]",
        re.IGNORECASE,
    )
)

# * Includes /, !, . — use in ConversationHandler fallbacks to catch all commands
ALL_PREFIXES_CMD_FILTER: filters.BaseFilter = filters.Regex(
    re.compile(
        rf"^[{re.escape(''.join(set(_get_prefixes())))}][a-zA-Z]",
        re.IGNORECASE,
    )
)


# ──────────────────────── Argument Parsing ──────────────────────── #


def parse_cmd_args(text: str | None) -> list[str]:
    """
    Extract arguments from a prefixed command message text.

    Mimics PTB's native argument parsing for alt-prefix commands.
    Returns an empty list if no text or no arguments are provided.
    """
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
