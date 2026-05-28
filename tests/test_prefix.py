# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Tests for tcbot.utils.prefixes command parsing and dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tcbot.utils import prefixes


class FakeMessage:
    def __init__(
        self, text: str | None, bot_username: str | None = "TargetBot"
    ) -> None:
        self.text = text
        self._bot = SimpleNamespace(username=bot_username)

    def get_bot(self):
        return self._bot


@pytest.fixture(autouse=True)
def _clear_registry():
    prefixes._REGISTRY.clear()
    yield
    prefixes._REGISTRY.clear()


# ──────────────────────── command parsing ───────────────────────── #


def test_parse_prefixed_command_accepts_lowercase_prefixes() -> None:
    for text in ("/start", "!start", ".start"):
        assert prefixes._parse_prefixed_command(text, ["/", "!", "."], "TargetBot") == (
            "start",
            None,
        )


def test_parse_prefixed_command_rejects_uppercase_command() -> None:
    for text in ("/START", "/Start", "!START", "!Start", ".START", ".Start"):
        assert (
            prefixes._parse_prefixed_command(text, ["/", "!", "."], "TargetBot") is None
        )


def test_parse_prefixed_command_accepts_self_bot_mention() -> None:
    assert prefixes._parse_prefixed_command(
        "/start@TargetBot", ["/", "!", "."], "TargetBot"
    ) == ("start", "TargetBot")


def test_parse_prefixed_command_accepts_self_bot_mention_case_insensitive() -> None:
    assert prefixes._parse_prefixed_command(
        "!start@targetbot", ["/", "!", "."], "TargetBot"
    ) == ("start", "targetbot")


def test_parse_prefixed_command_rejects_foreign_bot_mention() -> None:
    assert (
        prefixes._parse_prefixed_command(
            "/start@anythingbotnotself", ["/", "!", "."], "TargetBot"
        )
        is None
    )


def test_parse_prefixed_command_rejects_slash_when_only_custom_prefixes_allowed() -> (
    None
):
    assert prefixes._parse_prefixed_command("/start", ["!", "."], "TargetBot") is None


def test_parse_prefixed_command_rejects_digit_first_char() -> None:
    assert (
        prefixes._parse_prefixed_command(".1bad", ["/", "!", "."], "TargetBot") is None
    )


# ───────────────────────── command filters ───────────────────────── #


def test_build_prefixed_filters_accepts_lowercase_command_for_self_bot() -> None:
    command_filter = prefixes.build_prefixed_filters("start")
    assert command_filter.filter(FakeMessage("/start@TargetBot")) is True


def test_build_prefixed_filters_rejects_uppercase_command() -> None:
    command_filter = prefixes.build_prefixed_filters("start")
    assert command_filter.filter(FakeMessage("/Start@TargetBot")) is False


def test_build_prefixed_filters_rejects_foreign_bot_mention() -> None:
    command_filter = prefixes.build_prefixed_filters("start")
    assert command_filter.filter(FakeMessage("/start@OtherBot")) is False


# ───────────────────────── parse_cmd_args ───────────────────────── #


def test_parse_cmd_args_returns_args_after_command() -> None:
    assert prefixes.parse_cmd_args(".cban 42 spam links") == ["42", "spam", "links"]


def test_parse_cmd_args_returns_empty_for_bare_command() -> None:
    assert prefixes.parse_cmd_args(".cban") == []


def test_parse_cmd_args_returns_empty_for_none() -> None:
    assert prefixes.parse_cmd_args(None) == []


# ─────────────────────── dispatch_alt_prefix ────────────────────── #


async def test_dispatch_routes_to_registered_callback() -> None:
    seen: dict = {}

    async def cb(update, context) -> None:
        seen["args"] = list(context.args)

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=FakeMessage(".cban 42 spam"))
    ctx = SimpleNamespace(args=[])
    await prefixes.dispatch_alt_prefix(update, ctx)
    assert seen["args"] == ["42", "spam"]


async def test_dispatch_accepts_self_bot_mention() -> None:
    called: list[str] = []

    async def cb(update, context) -> None:
        called.append("hit")

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=FakeMessage("!cban@TargetBot"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
    assert called == ["hit"]


async def test_dispatch_ignores_uppercase_command() -> None:
    called: list[str] = []

    async def cb(update, context) -> None:
        called.append("hit")

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=FakeMessage("!CBAN"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
    assert called == []


async def test_dispatch_ignores_foreign_bot_mention() -> None:
    called: list[str] = []

    async def cb(update, context) -> None:
        called.append("hit")

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=FakeMessage("!cban@OtherBot"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
    assert called == []


async def test_dispatch_ignores_unknown_command_silently() -> None:
    update = SimpleNamespace(effective_message=FakeMessage(".unknown"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))


async def test_dispatch_ignores_message_without_text() -> None:
    update = SimpleNamespace(effective_message=FakeMessage(None))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))


async def test_dispatch_swallows_handler_exception() -> None:
    async def boom(update, context) -> None:
        raise RuntimeError("crash")

    prefixes.register_command("crash", boom)
    update = SimpleNamespace(effective_message=FakeMessage(".crash"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
