# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Command filter builder for all configured prefixes (/, !, .) and alt-prefix dispatcher."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from telegram import Message
from telegram.ext import filters

from tcbot import cfg

log = logging.getLogger(__name__)


class _BotLike(Protocol):
    username: str | None


class _MessageLike(Protocol):
    text: str | None

    def get_bot(self) -> _BotLike: ...


class _UpdateLike(Protocol):
    effective_message: _MessageLike | None


class _ContextLike(Protocol):
    args: list[str]


# ─────────────────────── Alt-Prefix Registry ────────────────────── #
# * Stores callbacks for non-slash prefixed commands (!cmd, .cmd)

_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}


def register_command(
    name: str, callback: Callable[..., Coroutine[Any, Any, None]]
) -> None:
    """Register an async callback for a lowercase command name."""
    _REGISTRY[name.lower()] = callback


async def dispatch_alt_prefix(update: _UpdateLike, context: _ContextLike) -> None:
    """Dispatch an update to a registered alt-prefix command handler."""
    msg = getattr(update, "effective_message", None)
    if not msg:
        return
    text: str | None = getattr(msg, "text", None)
    if not text:
        return

    parsed = _parse_prefixed_command(
        text,
        _get_custom_prefixes(),
        _bot_username_from_message(msg),
    )
    if parsed is None:
        return

    cmd, _mention = parsed
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
    """Return command prefixes from the already-validated runtime configuration."""
    return cfg.prefixes or ["/"]


def _get_custom_prefixes() -> list[str]:
    """Return configured prefixes excluding the native Telegram slash (/)."""
    return [p for p in _get_prefixes() if p != "/"]


def _never_match_filter() -> filters.BaseFilter:
    """Return a valid filter that intentionally never matches any message text."""
    return filters.Regex(re.compile(r"a^"))


def _bot_username_from_message(message: _MessageLike) -> str | None:
    """Return the current bot username from a PTB message when available."""
    try:
        bot = message.get_bot()
    except (AttributeError, RuntimeError):
        return None
    return (getattr(bot, "username", None) or "").lstrip("@") or None


def _parse_prefixed_command(
    text: str,
    prefixes: list[str],
    bot_username: str | None,
) -> tuple[str, str | None] | None:
    """Parse a lowercase prefixed command and validate any bot mention suffix."""
    if not prefixes:
        return None

    prefix = next(
        (p for p in sorted(set(prefixes), key=len, reverse=True) if text.startswith(p)),
        None,
    )
    if prefix is None:
        return None

    _parts = text[len(prefix) :].split(None, 1)
    if not _parts:
        return None
    token = _parts[0]
    if not token:
        return None

    command, separator, mention = token.partition("@")
    if not command or command != command.lower() or not command.isascii():
        return None
    if not re.fullmatch(r"[a-z][a-z0-9]*", command):
        return None
    if separator:
        if not mention or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", mention):
            return None
        if bot_username is None or mention.casefold() != bot_username.casefold():
            return None

    return command, mention or None


class _PrefixedCommandFilter(filters.MessageFilter):
    """PTB message filter for exact lowercase commands and self-only bot mentions."""

    def __init__(self, command: str, prefixes: list[str]) -> None:
        super().__init__(name=f"PrefixedCommand({command})")
        self.command = command
        self.prefixes = prefixes

    def filter(self, message: Message) -> bool:
        """Return True when the message matches this filter's specific command."""
        text = message.text or ""
        parsed = _parse_prefixed_command(
            text,
            self.prefixes,
            _bot_username_from_message(message),
        )
        return parsed is not None and parsed[0] == self.command


class _AnyPrefixedCommandFilter(filters.MessageFilter):
    """PTB message filter for any valid lowercase command with configured prefixes."""

    def __init__(self, prefixes: list[str], *, name: str) -> None:
        super().__init__(name=name)
        self.prefixes = prefixes

    def filter(self, message: Message) -> bool:
        """Return True when the message is any valid prefixed command."""
        text = message.text or ""
        return (
            _parse_prefixed_command(
                text,
                self.prefixes,
                _bot_username_from_message(message),
            )
            is not None
        )


# ───────────────────────── Filter Builders ──────────────────────── #


def build_prefixed_filters(command: str) -> filters.BaseFilter:
    """Return a filter matching exact lowercase <prefix><command> for configured prefixes."""
    return _PrefixedCommandFilter(command.lower(), _get_prefixes())


# * Matches !, . etc.; does NOT match Telegram-native /commands
# * Used in __main__.py member-cache guard (intentionally excludes /)
_custom_prefixes = _get_custom_prefixes()
ANY_CMD_FILTER: filters.BaseFilter = (
    _AnyPrefixedCommandFilter(_custom_prefixes, name="AnyCustomPrefixedCommand")
    if _custom_prefixes
    else _never_match_filter()
)

# * Includes /, !, .; use in ConversationHandler fallbacks to catch all commands
_prefixes = _get_prefixes()
ALL_PREFIXES_CMD_FILTER: filters.BaseFilter = (
    _AnyPrefixedCommandFilter(_prefixes, name="AnyPrefixedCommand")
    if _prefixes
    else _never_match_filter()
)


# ──────────────────────── Argument Parsing ──────────────────────── #


def parse_cmd_args(text: str | None) -> list[str]:
    """Extract arguments from a prefixed command message text."""
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
