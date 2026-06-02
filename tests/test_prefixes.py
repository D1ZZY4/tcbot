"""Tests for tcbot.utils.prefixes — pure parsing helpers."""

from __future__ import annotations

from tcbot.utils.prefixes import (
    _REGISTRY,
    _parse_prefixed_command,
    dispatch_alt_prefix,
    parse_cmd_args,
    register_command,
)

# ──────────────────────────── _parse_prefixed_command ────────────────────────── #


class TestParsePrefixedCommand:
    def test_slash_command_parsed(self) -> None:
        result = _parse_prefixed_command("/ban", ["/"], None)
        assert result == ("ban", None)

    def test_bang_prefix_parsed(self) -> None:
        result = _parse_prefixed_command("!mute", ["!"], None)
        assert result == ("mute", None)

    def test_dot_prefix_parsed(self) -> None:
        result = _parse_prefixed_command(".warn", ["."], None)
        assert result == ("warn", None)

    def test_multiple_prefixes_slash_matched(self) -> None:
        result = _parse_prefixed_command("/kick", ["/", "!", "."], None)
        assert result == ("kick", None)

    def test_multiple_prefixes_bang_matched(self) -> None:
        result = _parse_prefixed_command("!kick", ["/", "!", "."], None)
        assert result == ("kick", None)

    def test_no_matching_prefix_returns_none(self) -> None:
        result = _parse_prefixed_command("ban", ["/", "!"], None)
        assert result is None

    def test_empty_prefixes_returns_none(self) -> None:
        result = _parse_prefixed_command("/ban", [], None)
        assert result is None

    def test_command_with_args_parsed(self) -> None:
        result = _parse_prefixed_command("/ban 123 spamming", ["/"], None)
        assert result == ("ban", None)

    def test_command_with_valid_bot_mention(self) -> None:
        result = _parse_prefixed_command("/ban@mybot", ["/"], "mybot")
        assert result == ("ban", "mybot")

    def test_command_with_bot_mention_case_insensitive(self) -> None:
        result = _parse_prefixed_command("/ban@MyBot", ["/"], "mybot")
        assert result == ("ban", "MyBot")

    def test_command_with_wrong_bot_mention_returns_none(self) -> None:
        result = _parse_prefixed_command("/ban@otherbot", ["/"], "mybot")
        assert result is None

    def test_command_with_bot_mention_but_no_bot_username_returns_none(self) -> None:
        result = _parse_prefixed_command("/ban@mybot", ["/"], None)
        assert result is None

    def test_uppercase_command_returns_none(self) -> None:
        result = _parse_prefixed_command("/Ban", ["/"], None)
        assert result is None

    def test_non_ascii_command_returns_none(self) -> None:
        result = _parse_prefixed_command("/bán", ["/"], None)
        assert result is None

    def test_empty_command_after_prefix_returns_none(self) -> None:
        result = _parse_prefixed_command("/", ["/"], None)
        assert result is None

    def test_command_starting_with_digit_returns_none(self) -> None:
        result = _parse_prefixed_command("/1ban", ["/"], None)
        assert result is None

    def test_command_with_at_but_empty_mention_returns_none(self) -> None:
        result = _parse_prefixed_command("/ban@", ["/"], "mybot")
        assert result is None

    def test_command_with_too_short_mention_returns_none(self) -> None:
        result = _parse_prefixed_command("/ban@ab", ["/"], "ab")
        assert result is None

    def test_alphanumeric_command_accepted(self) -> None:
        result = _parse_prefixed_command("/ban2", ["/"], None)
        assert result == ("ban2", None)

    def test_longer_prefix_takes_precedence(self) -> None:
        result = _parse_prefixed_command("!!cmd", ["!", "!!"], None)
        assert result == ("cmd", None)

    def test_no_text_after_prefix_and_whitespace_returns_none(self) -> None:
        result = _parse_prefixed_command("!   ", ["!"], None)
        assert result is None

    def test_command_with_mention_too_long_returns_none(self) -> None:
        long_mention = "a" * 33
        result = _parse_prefixed_command(f"/ban@{long_mention}", ["/"], long_mention)
        assert result is None

    def test_valid_mention_exactly_5_chars(self) -> None:
        result = _parse_prefixed_command("/ban@mybOt", ["/"], "mybOt")
        assert result == ("ban", "mybOt")


# ──────────────────────────── parse_cmd_args ──────────────────────────────── #


class TestParseCmdArgs:
    def test_no_args_returns_empty(self) -> None:
        assert parse_cmd_args("/ban") == []

    def test_single_arg(self) -> None:
        assert parse_cmd_args("/ban 123") == ["123"]

    def test_multiple_args(self) -> None:
        assert parse_cmd_args("/ban 123 spamming hard") == ["123", "spamming", "hard"]

    def test_none_input_returns_empty(self) -> None:
        assert parse_cmd_args(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_cmd_args("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert parse_cmd_args("   ") == []

    def test_slash_only_no_args(self) -> None:
        assert parse_cmd_args("/") == []

    def test_args_with_extra_spaces_normalized(self) -> None:
        result = parse_cmd_args("/ban  123   456")
        assert result == ["123", "456"]

    def test_alt_prefix_args_parsed(self) -> None:
        result = parse_cmd_args("!mute 123 2h spamming")
        assert result == ["123", "2h", "spamming"]


# ──────────────────────────── register_command ──────────────────────────── #


class TestRegisterCommand:
    def test_register_adds_to_registry(self) -> None:
        async def fake_handler(u, c) -> None:
            pass

        register_command("testcmd", fake_handler)
        assert _REGISTRY.get("testcmd") is fake_handler

    def test_register_lowercases_name(self) -> None:
        async def fake_handler2(u, c) -> None:
            pass

        register_command("UPPER", fake_handler2)
        assert _REGISTRY.get("upper") is fake_handler2
        assert "UPPER" not in _REGISTRY


# ──────────────────────────── dispatch_alt_prefix ────────────────────────── #


class TestDispatchAltPrefix:
    async def test_no_effective_message_skips(self) -> None:
        class FakeUpdate:
            effective_message = None

        class FakeCtx:
            args: list[str] = []

        await dispatch_alt_prefix(FakeUpdate(), FakeCtx())

    async def test_no_text_skips(self) -> None:
        class FakeMsg:
            text = None

            def get_bot(self):
                class FakeBot:
                    username = "mybot"

                return FakeBot()

        class FakeUpdate:
            effective_message = FakeMsg()

        class FakeCtx:
            args: list[str] = []

        await dispatch_alt_prefix(FakeUpdate(), FakeCtx())

    async def test_unregistered_command_skips(self, monkeypatch) -> None:
        monkeypatch.setattr("tcbot.utils.prefixes.cfg", type("C", (), {"prefixes": ["!"]})())

        class FakeMsg:
            text = "!unknowncmd123"

            def get_bot(self):
                class FakeBot:
                    username = "mybot"

                return FakeBot()

        class FakeUpdate:
            effective_message = FakeMsg()

        class FakeCtx:
            args: list[str] = []

        await dispatch_alt_prefix(FakeUpdate(), FakeCtx())

    async def test_registered_command_called(self, monkeypatch) -> None:
        monkeypatch.setattr("tcbot.utils.prefixes.cfg", type("C", (), {"prefixes": ["!"]})())

        called_with: list = []

        async def fake_handler(u, c) -> None:
            called_with.append((u, c))

        _REGISTRY["testdispatch"] = fake_handler

        class FakeMsg:
            text = "!testdispatch arg1 arg2"

            def get_bot(self):
                class FakeBot:
                    username = None

                return FakeBot()

        class FakeUpdate:
            effective_message = FakeMsg()

        class FakeCtx:
            args: list[str] = []

        await dispatch_alt_prefix(FakeUpdate(), FakeCtx())
        assert len(called_with) == 1

    async def test_registered_command_handler_exception_swallowed(self, monkeypatch) -> None:
        monkeypatch.setattr("tcbot.utils.prefixes.cfg", type("C", (), {"prefixes": ["!"]})())

        async def raising_handler(u, c) -> None:
            raise RuntimeError("boom")

        _REGISTRY["testcrash"] = raising_handler

        class FakeMsg:
            text = "!testcrash"

            def get_bot(self):
                class FakeBot:
                    username = None

                return FakeBot()

        class FakeUpdate:
            effective_message = FakeMsg()

        class FakeCtx:
            args: list[str] = []

        await dispatch_alt_prefix(FakeUpdate(), FakeCtx())
