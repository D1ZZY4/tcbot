# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.stats - module metadata and help structure."""

from __future__ import annotations

import tcbot.modules.stats as stats

# ───────────────────────── Module metadata ──────────────────────── #


def test_module_name_is_stats() -> None:
    assert stats.__module_name__ == "Stats"


def test_help_text_is_non_empty() -> None:
    assert isinstance(stats.__help_text__, str)
    assert stats.__help_text__.strip()


def test_help_text_mentions_stats_or_federation() -> None:
    text = stats.__help_text__.lower()
    assert "stat" in text or "federation" in text


def test_help_sections_is_list_of_tuples() -> None:
    sections = stats.__help_sections__
    assert isinstance(sections, list)
    assert len(sections) > 0
    for item in sections:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_help_sections_keys_are_non_empty_strings() -> None:
    for key, value in stats.__help_sections__:
        assert isinstance(key, str) and key.strip()
        assert isinstance(value, str) and value.strip()


def test_help_sections_contains_commands_entry() -> None:
    keys = [k for k, _ in stats.__help_sections__]
    assert "Commands & Aliases" in keys


def test_help_sections_contains_who_can_use() -> None:
    keys = [k for k, _ in stats.__help_sections__]
    assert "Who can use" in keys


def test_help_sections_commands_mentions_tcstats() -> None:
    lookup = dict(stats.__help_sections__)
    assert "tcstats" in lookup["Commands & Aliases"]


def test_help_sections_commands_mentions_tcs_alias() -> None:
    lookup = dict(stats.__help_sections__)
    assert "/tcs" in lookup["Commands & Aliases"]


def test_help_sections_contains_drill_downs() -> None:
    keys = [k for k, _ in stats.__help_sections__]
    assert "Drill-downs" in keys


def test_help_sections_drill_downs_mentions_staff_roster() -> None:
    lookup = dict(stats.__help_sections__)
    assert "Staff Roster" in lookup["Drill-downs"]


def test_help_sections_drill_downs_mentions_connected_chats() -> None:
    lookup = dict(stats.__help_sections__)
    assert "Connected Chats" in lookup["Drill-downs"]


def test_help_sections_no_emdash() -> None:
    for _key, value in stats.__help_sections__:
        assert "\u2014" not in value


def test_help_sections_keys_unique() -> None:
    keys = [k for k, _ in stats.__help_sections__]
    assert len(keys) == len(set(keys))


# ───────────────────────────── Handlers ─────────────────────────── #


def test_handlers_list_is_non_empty() -> None:
    assert isinstance(stats.__handlers__, list)
    assert len(stats.__handlers__) >= 1


def test_handlers_include_callback_handler() -> None:
    from telegram.ext import CallbackQueryHandler

    cb_handlers = [h for h in stats.__handlers__ if isinstance(h, CallbackQueryHandler)]
    assert len(cb_handlers) >= 1


# ───────────────────── cmd_stats behaviour ──────────────────────── #

_cmd_stats = stats.cmd_stats.__wrapped__.__wrapped__


async def test_cmd_stats_calls_stats_main() -> None:
    """cmd_stats must call Stats.main() and reply with the returned text and keyboard."""
    from unittest.mock import AsyncMock, MagicMock, patch

    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg
    ctx = MagicMock()

    text = "<b>Federation Stats</b>"
    kb = MagicMock()

    with patch("tcbot.modules.stats.Stats") as MockStats:
        MockStats.main = AsyncMock(return_value=(text, kb))
        await _cmd_stats(update, ctx)

    MockStats.main.assert_called_once()
    msg.reply_text.assert_called_once_with(text, parse_mode="HTML", reply_markup=kb)


async def test_cmd_stats_uses_html_parse_mode() -> None:
    """cmd_stats must always reply with parse_mode='HTML'."""
    from unittest.mock import AsyncMock, MagicMock, patch

    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg
    ctx = MagicMock()

    with patch("tcbot.modules.stats.Stats") as MockStats:
        MockStats.main = AsyncMock(return_value=("<b>ok</b>", None))
        await _cmd_stats(update, ctx)

    kwargs = msg.reply_text.call_args[1]
    assert kwargs.get("parse_mode") == "HTML"


async def test_cmd_stats_passes_reply_markup_from_stats_main() -> None:
    """cmd_stats must forward the keyboard object returned by Stats.main()."""
    from unittest.mock import AsyncMock, MagicMock, patch

    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg
    ctx = MagicMock()

    kb = MagicMock()

    with patch("tcbot.modules.stats.Stats") as MockStats:
        MockStats.main = AsyncMock(return_value=("text", kb))
        await _cmd_stats(update, ctx)

    kwargs = msg.reply_text.call_args[1]
    assert kwargs.get("reply_markup") is kb
