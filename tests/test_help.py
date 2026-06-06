# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.help - help content builder and module-level state."""

from __future__ import annotations

import re

from tcbot.modules.help import (
    HELP_CONTENT,
    HELP_TOPICS_CMD,
    HELP_TOPICS_MENU,
)

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]")
_EMDASH_RE = re.compile(r"\u2014|\u2013")


# ────────────────────── HELP_CONTENT structure ──────────────────── #


def test_help_content_is_non_empty() -> None:
    """At least one module must expose help content."""
    assert HELP_CONTENT, "HELP_CONTENT is empty - no modules loaded"


def test_help_content_keys_prefixed_with_help() -> None:
    """All keys must follow the 'help_<module>' naming convention."""
    for key in HELP_CONTENT:
        assert key.startswith("help_"), f"Key {key!r} does not start with 'help_'"


def test_help_content_values_are_triples() -> None:
    """Each value must be (display_name, overview_text, sections)."""
    for key, val in HELP_CONTENT.items():
        assert isinstance(val, tuple) and len(val) == 3, (
            f"Entry {key!r} is not a 3-tuple"
        )


def test_help_content_display_names_non_empty() -> None:
    for key, (name, _, _) in HELP_CONTENT.items():
        assert name and name.strip(), f"Empty display name for {key!r}"


def test_help_content_overview_texts_non_empty() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert text and text.strip(), f"Empty overview text for {key!r}"


def test_help_content_sections_are_lists() -> None:
    for key, (_, _, sections) in HELP_CONTENT.items():
        assert isinstance(sections, list), f"Sections for {key!r} are not a list"


def test_help_content_section_entries_are_string_pairs() -> None:
    """Every section entry must be a (heading, body) string pair."""
    for key, (_, _, sections) in HELP_CONTENT.items():
        for i, entry in enumerate(sections):
            assert (
                isinstance(entry, tuple)
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
            ), f"Section {i} of {key!r} is malformed: {entry!r}"


def test_help_content_no_emoji_in_overview_texts() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert not _EMOJI_RE.search(text), f"Emoji in overview of {key!r}: {text!r}"


def test_help_content_no_em_dash_in_overview_texts() -> None:
    for key, (_, text, _) in HELP_CONTENT.items():
        assert not _EMDASH_RE.search(text), f"Em-dash in overview of {key!r}: {text!r}"


# ─────────────────── HELP_TOPICS_MENU / CMD ─────────────────────── #


def test_topics_menu_non_empty() -> None:
    assert HELP_TOPICS_MENU, "HELP_TOPICS_MENU is empty"


def test_topics_cmd_non_empty() -> None:
    assert HELP_TOPICS_CMD, "HELP_TOPICS_CMD is empty"


def test_topics_menu_same_length_as_help_content() -> None:
    assert len(HELP_TOPICS_MENU) == len(HELP_CONTENT)


def test_topics_cmd_same_length_as_help_content() -> None:
    assert len(HELP_TOPICS_CMD) == len(HELP_CONTENT)


def test_topics_menu_entries_are_name_key_pairs() -> None:
    for entry in HELP_TOPICS_MENU:
        assert isinstance(entry, tuple) and len(entry) == 2
        name, key = entry
        assert name and key
        assert key.startswith("help_")


def test_topics_cmd_entries_use_helpc_prefix() -> None:
    """Command-path topics must use 'helpc_' callback prefix."""
    for entry in HELP_TOPICS_CMD:
        _, key = entry
        assert key.startswith("helpc_"), f"CMD key {key!r} lacks 'helpc_' prefix"


def test_topics_menu_sorted_by_display_name() -> None:
    """Topics menu must be alphabetically sorted (case-insensitive)."""
    names = [name for name, _ in HELP_TOPICS_MENU]
    assert names == sorted(names, key=str.lower), "HELP_TOPICS_MENU is not sorted"


def test_topics_cmd_display_names_match_menu() -> None:
    """CMD topics must have the same display names as the menu topics."""
    menu_names = {name for name, _ in HELP_TOPICS_MENU}
    cmd_names = {name for name, _ in HELP_TOPICS_CMD}
    assert menu_names == cmd_names


def test_topics_cmd_keys_derived_from_menu_keys() -> None:
    """helpc_<slug> must match a corresponding help_<slug> entry."""
    menu_keys = {key for _, key in HELP_TOPICS_MENU}
    for _, cmd_key in HELP_TOPICS_CMD:
        slug = cmd_key[6:]  # strip "helpc_"
        assert f"help_{slug}" in menu_keys, (
            f"CMD key {cmd_key!r} has no matching menu entry"
        )


# ─────────────── callback handler behaviour ─────────────────────── #

import tcbot.modules.help as _help_mod  # noqa: E402

_on_help_menu = _help_mod.on_help_menu.__wrapped__.__wrapped__
_on_helpc_main = _help_mod.on_helpc_main.__wrapped__.__wrapped__
_on_help_menu_group = _help_mod.on_help_menu_group.__wrapped__.__wrapped__
_on_help_topic_any = _help_mod.on_help_topic_any.__wrapped__.__wrapped__
_on_help_section = _help_mod.on_help_section.__wrapped__.__wrapped__


def _make_help_cb(*, data: str = "help_menu", first_name: str = "Bot"):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    q = AsyncMock()
    q.data = data
    q.answer = AsyncMock(return_value=None)

    update = MagicMock()
    update.callback_query = q

    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.first_name = first_name

    return SimpleNamespace(update=update, ctx=ctx, q=q)


async def test_on_help_menu_group_answers_with_show_alert() -> None:
    """on_help_menu_group must answer with show_alert=True and never edit the message."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="help_menu_group")
    with patch("tcbot.modules.help.safe_edit_cb", new=AsyncMock()) as mock_edit:
        await _on_help_menu_group(env.update, env.ctx)
    env.q.answer.assert_called_once()
    assert env.q.answer.call_args[1].get("show_alert") is True
    mock_edit.assert_not_called()


async def test_on_help_menu_answers_callback_query() -> None:
    """on_help_menu must call q.answer() (gathered with safe_edit_cb)."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="help_menu")
    with patch("tcbot.modules.help.safe_edit_cb", new=AsyncMock()):
        await _on_help_menu(env.update, env.ctx)
    env.q.answer.assert_called_once()


async def test_on_helpc_main_answers_callback_query() -> None:
    """on_helpc_main must call q.answer() (gathered with safe_edit_cb)."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="helpc_main")
    with patch("tcbot.modules.help.safe_edit_cb", new=AsyncMock()):
        await _on_helpc_main(env.update, env.ctx)
    env.q.answer.assert_called_once()


async def test_on_help_topic_any_helpc_prefix_routes_to_menu_path_false() -> None:
    """on_help_topic_any with helpc_ data must call _show_module with is_menu_path=False."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="helpc_banning")
    with patch("tcbot.modules.help._show_module", new=AsyncMock()) as mock_show:
        await _on_help_topic_any(env.update, env.ctx)
    mock_show.assert_called_once()
    args, kwargs = mock_show.call_args
    assert kwargs.get("is_menu_path") is False
    assert args[1] == "help_banning"


async def test_on_help_topic_any_help_prefix_routes_to_menu_path_true() -> None:
    """on_help_topic_any with help_ data must call _show_module with is_menu_path=True."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="help_banning")
    with patch("tcbot.modules.help._show_module", new=AsyncMock()) as mock_show:
        await _on_help_topic_any(env.update, env.ctx)
    mock_show.assert_called_once()
    args, kwargs = mock_show.call_args
    assert kwargs.get("is_menu_path") is True
    assert args[1] == "help_banning"


async def test_on_help_section_malformed_data_answers_alert() -> None:
    """on_help_section with data containing no colon must answer with show_alert=True."""
    env = _make_help_cb(data="helps_NOCOLON")
    await _on_help_section(env.update, env.ctx)
    env.q.answer.assert_called_once()
    assert env.q.answer.call_args[1].get("show_alert") is True


async def test_on_help_section_valid_data_delegates_to_show_section() -> None:
    """on_help_section with valid helps_<mod>:<idx> data must call _show_section."""
    from unittest.mock import AsyncMock, patch

    env = _make_help_cb(data="helps_banning:0")
    with patch("tcbot.modules.help._show_section", new=AsyncMock()) as mock_sec:
        await _on_help_section(env.update, env.ctx)
    mock_sec.assert_called_once()
    args, _ = mock_sec.call_args
    assert args[0] is env.q
    assert args[1] == "banning"
    assert args[2] == 0


# ─────────────────── command handler: cmd_help ──────────────────── #

_cmd_help = _help_mod.cmd_help.__wrapped__.__wrapped__


def _make_cmd_ctx(text: str = "/help") -> tuple:
    from unittest.mock import AsyncMock, MagicMock

    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg
    ctx = MagicMock()
    ctx.bot.first_name = "TCFBot"
    return update, ctx


async def test_cmd_help_no_args_sends_help_index() -> None:
    """Calling /help with no argument sends the full help index reply."""
    update, ctx = _make_cmd_ctx("/help")
    await _cmd_help(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = update.effective_message.reply_text.call_args[1]
    assert call_kwargs.get("parse_mode") == "HTML"
    assert call_kwargs.get("reply_markup") is not None


async def test_cmd_help_known_module_sends_module_overview() -> None:
    """Calling /help banning (a known module) sends that module's help text."""
    update, ctx = _make_cmd_ctx("/help banning")
    await _cmd_help(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "<b>" in reply_text  # HTML module help was sent


async def test_cmd_help_unknown_module_sends_not_found() -> None:
    """Calling /help with an unrecognised argument sends a 'not found' message."""
    update, ctx = _make_cmd_ctx("/help zzznonsense999")
    await _cmd_help(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "not found" in reply_text
