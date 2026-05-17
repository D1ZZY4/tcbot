# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""
Tests for tcbot.utils.prefixes dispatcher and regex.
"""

from __future__ import annotations

from types import SimpleNamespace
import pytest

from tcbot.utils import prefixes


@pytest.fixture(autouse=True)
def _clear_registry():
    prefixes._REGISTRY.clear()
    yield
    prefixes._REGISTRY.clear()


## ── _ALT_RE ────────────────────────────────────────────────────────────────

def test_alt_re_accepts_dot_prefix() -> None:
    assert prefixes._ALT_RE.match(".cban target")


def test_alt_re_accepts_bang_prefix() -> None:
    assert prefixes._ALT_RE.match("!cban")


def test_alt_re_accepts_at_bot_suffix() -> None:
    assert prefixes._ALT_RE.match(".cban@MyBot 1 spam")


def test_alt_re_rejects_slash_prefix() -> None:
    assert prefixes._ALT_RE.match("/cban target") is None


def test_alt_re_rejects_digit_first_char() -> None:
    assert prefixes._ALT_RE.match(".1bad") is None


## ── parse_cmd_args ─────────────────────────────────────────────────────────

def test_parse_cmd_args_returns_args_after_command() -> None:
    assert prefixes.parse_cmd_args(".cban 42 spam links") == ["42", "spam", "links"]


def test_parse_cmd_args_returns_empty_for_bare_command() -> None:
    assert prefixes.parse_cmd_args(".cban") == []


def test_parse_cmd_args_returns_empty_for_none() -> None:
    assert prefixes.parse_cmd_args(None) == []


## ── dispatch_alt_prefix ────────────────────────────────────────────────────

async def test_dispatch_routes_to_registered_callback() -> None:
    seen: dict = {}

    async def cb(update, context) -> None:
        seen["args"] = list(context.args)

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=SimpleNamespace(text=".cban 42 spam"))
    ctx = SimpleNamespace(args=[])
    await prefixes.dispatch_alt_prefix(update, ctx)
    assert seen["args"] == ["42", "spam"]


async def test_dispatch_lowercases_command() -> None:
    called: list = []

    async def cb(update, context) -> None:
        called.append("hit")

    prefixes.register_command("cban", cb)
    update = SimpleNamespace(effective_message=SimpleNamespace(text="!CBAN"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
    assert called == ["hit"]


async def test_dispatch_ignores_unknown_command_silently() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(text=".unknown"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))


async def test_dispatch_ignores_message_without_text() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(text=None))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))


async def test_dispatch_swallows_handler_exception() -> None:
    async def boom(update, context) -> None:
        raise RuntimeError("crash")

    prefixes.register_command("crash", boom)
    update = SimpleNamespace(effective_message=SimpleNamespace(text=".crash"))
    await prefixes.dispatch_alt_prefix(update, SimpleNamespace(args=[]))
