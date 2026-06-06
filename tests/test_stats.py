# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

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


# ─────────────── callback handler behaviour ─────────────────────── #

from tcbot.modules.helper.workflows.stats_flow import (  # noqa: E402
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
)

_on_stats_main = stats.on_stats_main.__wrapped__.__wrapped__
_on_stats_admins = stats.on_stats_admins.__wrapped__.__wrapped__
_on_stats_bans = stats.on_stats_bans.__wrapped__.__wrapped__
_on_stats_bans_search = stats.on_stats_bans_search.__wrapped__.__wrapped__
_on_stats_search_cancel = stats.on_stats_search_cancel.__wrapped__.__wrapped__
_on_bans_search_input = stats.on_bans_search_input.__wrapped__.__wrapped__


def _make_cb_env(*, data: str = "stats_main"):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    q = AsyncMock()
    q.data = data
    q.answer = AsyncMock(return_value=None)

    update = MagicMock()
    update.callback_query = q

    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = AsyncMock()

    return SimpleNamespace(update=update, ctx=ctx, q=q)


async def test_on_stats_main_calls_stats_main() -> None:
    """on_stats_main must call Stats.main() and edit the message with the result."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env()
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.main = AsyncMock(return_value=("<b>ok</b>", None))
        await _on_stats_main(env.update, env.ctx)
    MockStats.main.assert_called_once()


async def test_on_stats_admins_calls_staff_roster() -> None:
    """on_stats_admins must call Stats.staff_roster() to build the response."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_admins")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.staff_roster = AsyncMock(return_value=("<b>Staff</b>", None))
        await _on_stats_admins(env.update, env.ctx)
    MockStats.staff_roster.assert_called_once()


async def test_on_stats_bans_clears_search_before_bans_list() -> None:
    """on_stats_bans must call Stats.clear_search before calling Stats.bans_list."""
    from unittest.mock import AsyncMock, MagicMock, patch

    env = _make_cb_env(data="stats_bans:0")
    call_order: list[str] = []
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.clear_search = MagicMock(
            side_effect=lambda _ctx: call_order.append("clear")
        )

        async def _bans_list(page: int) -> tuple[str, None]:
            call_order.append("bans_list")
            return ("<b>Bans</b>", None)

        MockStats.bans_list = _bans_list
        await _on_stats_bans(env.update, env.ctx)
    assert call_order[0] == "clear"
    assert "bans_list" in call_order


async def test_on_stats_bans_passes_page_to_bans_list() -> None:
    """on_stats_bans must forward the parsed page number to Stats.bans_list."""
    from unittest.mock import AsyncMock, MagicMock, patch

    env = _make_cb_env(data="stats_bans:3")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.clear_search = MagicMock()
        MockStats.bans_list = AsyncMock(return_value=("<b>Bans p3</b>", None))
        await _on_stats_bans(env.update, env.ctx)
    MockStats.bans_list.assert_called_once_with(3)


async def test_on_stats_bans_search_calls_open_search_and_answers() -> None:
    """on_stats_bans_search must invoke Stats.open_search and acknowledge the query."""
    from unittest.mock import AsyncMock, MagicMock, patch

    env = _make_cb_env(data="stats_bans_search")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.open_search = MagicMock(return_value=("Search:", None))
        await _on_stats_bans_search(env.update, env.ctx)
    MockStats.open_search.assert_called_once()
    env.q.answer.assert_called_once()


async def test_on_stats_search_cancel_clears_and_loads_page_zero() -> None:
    """on_stats_search_cancel must clear search state and render the first bans page."""
    from unittest.mock import AsyncMock, MagicMock, patch

    env = _make_cb_env(data="stats_search_cancel")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.clear_search = MagicMock()
        MockStats.bans_list = AsyncMock(return_value=("<b>Bans</b>", None))
        await _on_stats_search_cancel(env.update, env.ctx)
    MockStats.clear_search.assert_called_once_with(env.ctx)
    MockStats.bans_list.assert_called_once_with(0)


async def test_on_bans_search_input_returns_early_without_search_key() -> None:
    """on_bans_search_input must return immediately when SEARCH_KEY is absent."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env()
    env.ctx.user_data = {}
    msg = AsyncMock()
    msg.text = "query"
    msg.delete = AsyncMock()
    env.update.effective_message = msg

    with patch("tcbot.modules.stats.Stats") as MockStats:
        MockStats.search_run = AsyncMock()
        await _on_bans_search_input(env.update, env.ctx)
    MockStats.search_run.assert_not_called()
    msg.delete.assert_not_called()


async def test_on_bans_search_input_runs_search_and_stores_results() -> None:
    """on_bans_search_input must run the search and write results into user_data."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env()
    env.ctx.user_data = {SEARCH_KEY: True, CHAT_KEY: -100, MSG_KEY: 5}
    msg = AsyncMock()
    msg.text = "alice"
    msg.delete = AsyncMock(return_value=None)
    env.update.effective_message = msg

    results = [{"user_id": 1}]
    with patch("tcbot.modules.stats.Stats") as MockStats:
        MockStats.search_run = AsyncMock(return_value=results)
        MockStats.search_results = AsyncMock(return_value=("<b>Results</b>", None))
        await _on_bans_search_input(env.update, env.ctx)
    assert env.ctx.user_data.get(RESULTS_KEY) == results
    MockStats.search_run.assert_called_once_with("alice")


# ─────── Handler behavior: remaining on_stats_* callback handlers ──── #

_on_stats_users = stats.on_stats_users.__wrapped__.__wrapped__
_on_stats_user_item = stats.on_stats_user_item.__wrapped__.__wrapped__
_on_stats_chats = stats.on_stats_chats.__wrapped__.__wrapped__
_on_stats_chat_item = stats.on_stats_chat_item.__wrapped__.__wrapped__
_on_stats_ban_item = stats.on_stats_ban_item.__wrapped__.__wrapped__
_on_stats_search_item = stats.on_stats_search_item.__wrapped__.__wrapped__
_on_stats_search_back = stats.on_stats_search_back.__wrapped__.__wrapped__


async def test_on_stats_users_calls_users_list() -> None:
    """on_stats_users must forward the parsed page to Stats.users_list."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_users:2")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.users_list = AsyncMock(return_value=("<b>Users</b>", None))
        await _on_stats_users(env.update, env.ctx)
    MockStats.users_list.assert_called_once_with(2)


async def test_on_stats_user_item_calls_user_detail() -> None:
    """on_stats_user_item must forward page and index to Stats.user_detail."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_user_item:1:3")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.user_detail = AsyncMock(return_value=("<b>Detail</b>", None))
        await _on_stats_user_item(env.update, env.ctx)
    MockStats.user_detail.assert_called_once_with(1, 3)


async def test_on_stats_chats_calls_chats_list() -> None:
    """on_stats_chats must forward the parsed page to Stats.chats_list."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_chats:0")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.chats_list = AsyncMock(return_value=("<b>Chats</b>", None))
        await _on_stats_chats(env.update, env.ctx)
    MockStats.chats_list.assert_called_once_with(0)


async def test_on_stats_chat_item_calls_chat_detail() -> None:
    """on_stats_chat_item must forward page and index to Stats.chat_detail."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_chat_item:0:2")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.chat_detail = AsyncMock(return_value=("<b>Chat</b>", None))
        await _on_stats_chat_item(env.update, env.ctx)
    MockStats.chat_detail.assert_called_once_with(0, 2)


async def test_on_stats_ban_item_calls_ban_detail() -> None:
    """on_stats_ban_item must forward page and index to Stats.ban_detail."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_ban_item:1:0")
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.ban_detail = AsyncMock(return_value=("<b>Ban</b>", None))
        await _on_stats_ban_item(env.update, env.ctx)
    MockStats.ban_detail.assert_called_once_with(1, 0)


async def test_on_stats_search_item_calls_search_detail_with_results() -> None:
    """on_stats_search_item must forward the stored results and index to Stats.search_detail."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_search_item:2")
    stored = [{"user_id": 10}, {"user_id": 20}, {"user_id": 30}]
    env.ctx.user_data = {RESULTS_KEY: stored}
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.search_detail = AsyncMock(return_value=("<b>Detail</b>", None))
        await _on_stats_search_item(env.update, env.ctx)
    MockStats.search_detail.assert_called_once_with(stored, 2)


async def test_on_stats_search_back_empty_results_opens_search() -> None:
    """on_stats_search_back must reopen the search prompt when no results are stored."""
    from unittest.mock import AsyncMock, MagicMock, patch

    env = _make_cb_env(data="stats_search_back")
    env.ctx.user_data = {}
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.open_search = MagicMock(return_value=("<b>Search</b>", None))
        await _on_stats_search_back(env.update, env.ctx)
    MockStats.open_search.assert_called_once()


async def test_on_stats_search_back_with_results_renders_search_results() -> None:
    """on_stats_search_back must re-render search results when results are stored."""
    from unittest.mock import AsyncMock, patch

    env = _make_cb_env(data="stats_search_back")
    stored = [{"user_id": 1}, {"user_id": 2}]
    env.ctx.user_data = {RESULTS_KEY: stored, "stats_last_query": "alice"}
    with (
        patch("tcbot.modules.stats.Stats") as MockStats,
        patch("tcbot.modules.stats.safe_edit_cb", new=AsyncMock()),
    ):
        MockStats.search_results = AsyncMock(return_value=("<b>Results</b>", None))
        await _on_stats_search_back(env.update, env.ctx)
    MockStats.search_results.assert_awaited_once_with("alice", stored)
