# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Build command filters that match all configured prefixes (/, !, .) and
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

_ALT_RE = re.compile(r"^[.!]([a-z][a-z0-9]*)(?:@\w+)?(?:\s|$)", re.IGNORECASE)

_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}


def register_command(name: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
    """Register an async callback for a given command name (case-insensitive)."""
    _REGISTRY[name.lower()] = callback


async def dispatch_alt_prefix(update: object, context: object) -> None:
    """Dispatch an update to a registered alt-prefix command handler.

    Parses the ``effective_message.text`` against :data:`_ALT_RE`, looks up
    the command in :data:`_REGISTRY`, injects ``context.args``, and calls the
    handler.  Any exception raised by the handler is swallowed (logged at
    WARNING level) to keep the dispatcher robust.
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
    context.args = parts[1].split() if len(parts) > 1 else []  # type: ignore[attr-defined]

    try:
        await callback(update, context)
    except Exception as exc:
        log.warning("dispatch_alt_prefix: handler %r raised %s", cmd, exc)


def _get_prefixes() -> list[str]:
    """Parse PREFIXES env var – handles both list format and plain string."""
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
    """Return configured prefixes excluding the native Telegram slash (/)."""
    return [p for p in _get_prefixes() if p != "/"]


def build_prefixed_filters(command: str) -> filters.BaseFilter:
    """Return a filter matching <prefix><command> for all configured prefixes."""
    prefixes = _get_prefixes()
    escaped_prefixes = re.escape("".join(set(prefixes)))
    pattern = rf"^[{escaped_prefixes}]{re.escape(command)}(?:@\w+)?(?:\s|$)"
    return filters.Regex(re.compile(pattern, re.IGNORECASE))


## Pre-computed filter: any text starting with a CUSTOM (non-slash) prefix followed by a letter.
## Matches !, . etc. — does NOT match Telegram-native /commands.
## Use in ConversationHandler fallbacks and as ~COMMAND guard in text-input states.
ANY_CMD_FILTER: filters.BaseFilter = filters.Regex(
    re.compile(
        rf"^[{re.escape(''.join(set(_get_custom_prefixes())))}][a-zA-Z]",
        re.IGNORECASE,
    )
)


def parse_cmd_args(text: str | None) -> list[str]:
    """Extract arguments from a prefixed command message text."""
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
