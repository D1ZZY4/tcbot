# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Command prefix parsing and filter matching."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

from tcbot.utils.prefixes import (
    _AnyPrefixedCommandFilter,
    _parse_prefixed_command,
    _PrefixedCommandFilter,
    parse_cmd_args,
)


def _message(text: str | None, username: str | None = "Bot") -> Any:
    """Build a duck-typed stand-in for a Kurigram message and client."""
    return SimpleNamespace(
        text=text,
        client=SimpleNamespace(me=SimpleNamespace(username=username)),
    )


def _matches(filt: Any, msg: Any) -> bool:
    """Evaluate a Kurigram filter against one message."""
    result = filt(msg.client, msg)
    return asyncio.run(result) if inspect.isawaitable(result) else bool(result)


def test_plain_command_parses() -> None:
    assert _parse_prefixed_command("/tcban 5", ("/", "!", "."), None) == (
        "tcban",
        None,
    )


def test_longest_prefix_wins() -> None:
    assert _parse_prefixed_command("..tcban", ("..", "."), None) == ("tcban", None)


def test_matching_mention_accepted_case_insensitive() -> None:
    assert _parse_prefixed_command("/tcb@mybot x", ("/",), "MyBot") == ("tcb", "mybot")


def test_wrong_mention_rejected() -> None:
    assert _parse_prefixed_command("/tcb@OtherBot", ("/",), "MyBot") is None


def test_uppercase_command_rejected() -> None:
    assert _parse_prefixed_command("/TCBAN", ("/",), None) is None


def test_unicode_command_rejected() -> None:
    assert _parse_prefixed_command("/tcbané", ("/",), None) is None


def test_missing_prefix_rejected() -> None:
    assert _parse_prefixed_command("tcban", ("/",), None) is None


def test_empty_prefixes_rejected() -> None:
    assert _parse_prefixed_command("/tcban", (), None) is None


def test_bare_prefix_rejected() -> None:
    assert _parse_prefixed_command("/", ("/",), None) is None


def test_prefix_separated_by_whitespace_rejected() -> None:
    """A space after the prefix is prose, not a command.

    Telegram does not treat "/ help" (or "/ warn me") as a command, and
    executing one would let ordinary chat text trigger a moderation flow.
    """
    assert _parse_prefixed_command("/ tcban", ("/",), None) is None
    assert _parse_prefixed_command("! tckick", ("!",), None) is None


def test_short_mention_rejected() -> None:
    assert _parse_prefixed_command("/tcb@ab", ("/",), "ab") is None


def test_prefix_filter_stays_on_the_event_loop() -> None:
    """Kurigram offloads sync filters; hundreds of leaves would cost a thread hop each."""
    filt = _PrefixedCommandFilter("tcban", ["/"])
    assert inspect.iscoroutinefunction(filt.__call__)


def test_filter_matches_configured_command() -> None:
    filt = _PrefixedCommandFilter("tcban", ["/", "!", "."])
    assert _matches(filt, _message("/tcban 5")) is True
    assert _matches(filt, _message("!tcban")) is True
    assert _matches(filt, _message("/tckick")) is False
    assert _matches(filt, _message("hello")) is False


def test_filter_accepts_own_mention_only() -> None:
    # * Telegram usernames need 5+ chars, so the fixture uses a long name.
    filt = _PrefixedCommandFilter("tcb", ["/"])
    assert _matches(filt, _message("/tcb@TestBot", "TestBot")) is True
    assert _matches(filt, _message("/tcb@OtherBot", "TestBot")) is False


def test_any_filter_matches_any_command() -> None:
    filt = _AnyPrefixedCommandFilter(["/"], name="Any")
    assert _matches(filt, _message("/tcban")) is True
    assert _matches(filt, _message("plain chat")) is False


def test_parse_cmd_args_splits() -> None:
    assert parse_cmd_args("/tcb 123 reason here") == ["123", "reason", "here"]


def test_parse_cmd_args_empty() -> None:
    assert parse_cmd_args("/tcb") == []
    assert parse_cmd_args(None) == []
    assert parse_cmd_args("") == []
