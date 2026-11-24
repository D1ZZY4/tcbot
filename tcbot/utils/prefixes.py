# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Command filter builder for all configured prefixes (/, !, .)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pyrogram import filters

from tcbot import cfg

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.filters import Filter

# * Precompiled: the parser runs on every incoming message, so the command
# * shapes must not recompile per call.
_COMMAND_RE = re.compile(r"[a-z][a-z0-9]*")
_MENTION_RE = re.compile(r"[A-Za-z0-9_]{5,32}")


# ──────────────────────── Prefix Resolution ─────────────────────── #


def _get_prefixes() -> list[str]:
    """Return command prefixes from the validated runtime configuration."""
    return [p for p in (cfg.prefixes or ["/"]) if p and p.strip()]


def _never_match_filter() -> Filter:
    """Return a valid filter that intentionally never matches a message."""
    return filters.create(lambda _, __, ___: False, name="NeverMatch")


def _parse_prefixed_command(
    text: str,
    prefixes: tuple[str, ...],
    bot_username: str | None,
) -> tuple[str, str | None] | None:
    """Parse a lowercase prefixed command and validate any bot mention suffix."""
    if not prefixes:
        return None
    prefix = next((p for p in prefixes if text.startswith(p)), None)
    if prefix is None:
        return None
    remainder = text[len(prefix) :]
    # * A leading space is not a command; accepting it executed moderation on
    # * ordinary prose such as "/ warn me".
    if not remainder or remainder[0].isspace():
        return None
    token = remainder.split(None, 1)[0]
    command, separator, mention = token.partition("@")
    if not command or not _COMMAND_RE.fullmatch(command):
        return None
    if separator:
        if not mention or not _MENTION_RE.fullmatch(mention):
            return None
        if bot_username is None or mention.casefold() != bot_username.casefold():
            return None
    return command, mention or None


def _bot_username(client: Client) -> str | None:
    """Return the current bot username when the client is authorised."""
    me = getattr(client, "me", None)
    return (getattr(me, "username", None) or "").lstrip("@") or None


def _matcher(command: str | None, prefixes: tuple[str, ...]) -> Filter:
    """Build a Kurigram filter matching one command or any prefixed command."""

    def check(_: Filter, client: Client, update: object) -> bool:
        message = getattr(update, "text", None)
        if message is None:
            return False
        text = str(message)
        username = _bot_username(client) if "@" in text else None
        parsed = _parse_prefixed_command(text, prefixes, username)
        if parsed is None:
            return False
        return command is None or parsed[0] == command

    name = f"PrefixedCommand({command})" if command else "AnyPrefixedCommand"
    return filters.create(check, name=name)


# ───────────────────────── Filter Builders ──────────────────────── #


def build_prefixed_filters(command: str) -> Filter:
    """Return a filter matching exact lowercase <prefix><command>."""
    return _matcher(
        command.lower(), tuple(sorted(_get_prefixes(), key=len, reverse=True))
    )


def _PrefixedCommandFilter(command: str, prefixes: list[str] | None = None) -> Filter:
    """Build a native filter for one command under the configured prefixes."""
    chosen = prefixes if prefixes is not None else _get_prefixes()
    return _matcher(command.lower(), tuple(sorted(chosen, key=len, reverse=True)))


def _AnyPrefixedCommandFilter(
    prefixes: list[str] | None = None, *, name: str = ""
) -> Filter:
    """Build a native filter matching any prefixed command."""
    chosen = prefixes if prefixes is not None else _get_prefixes()
    return _matcher(None, tuple(sorted(chosen, key=len, reverse=True)))


_prefixes = tuple(sorted(_get_prefixes(), key=len, reverse=True))
ALL_PREFIXES_CMD_FILTER: Filter = (
    _matcher(None, _prefixes) if _prefixes else _never_match_filter()
)

_ALL_COMMANDS: tuple[str, ...] = (
    "bc",
    "c",
    "check",
    "checkme",
    "cleanup",
    "clearwarns",
    "cme",
    "exitall",
    "help",
    "lang",
    "langs",
    "language",
    "leaveall",
    "p",
    "ping",
    "resetwarns",
    "rmtc",
    "rules",
    "speedtest",
    "st",
    "start",
    "tcb",
    "tcban",
    "tcbroadcast",
    "tcc",
    "tcclean",
    "tccon",
    "tcconnect",
    "tcd",
    "tcdemote",
    "tcdiscon",
    "tcdisconnect",
    "tcf",
    "tcforget",
    "tcplist",
    "tcg",
    "tcgroups",
    "tck",
    "tckick",
    "tcleave",
    "tcm",
    "tcmute",
    "tcp",
    "tcpromote",
    "tcpromotelist",
    "tcpromoterequests",
    "tcr",
    "tcrepair",
    "tcreqs",
    "tcrls",
    "tcrules",
    "tcs",
    "tcstats",
    "tcsetrole",
    "tcum",
    "tcunb",
    "tcunban",
    "tcunm",
    "tcunmute",
    "tcunw",
    "tcunwarn",
    "tcw",
    "tcwarn",
    "tfowner",
    "transferowner",
    "warnlist",
    "warns",
)


def build_conversation_escape_filter(*own_commands: str) -> Filter:
    """Return a filter for commands that bypass conversation fallbacks."""
    excluded = set(own_commands)
    combined: Filter | None = None
    for command in _ALL_COMMANDS:
        if command in excluded:
            continue
        one = build_prefixed_filters(command)
        combined = one if combined is None else combined | one
    return combined if combined is not None else _never_match_filter()


# ──────────────────────── Argument Parsing ──────────────────────── #


def parse_cmd_args(text: str | None) -> list[str]:
    """Extract arguments from a prefixed command message text."""
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
