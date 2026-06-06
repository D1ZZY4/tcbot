# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for stats_flow: pagination helpers and Stats class view builders."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tcbot.modules.helper.workflows import stats_flow
from tcbot.modules.helper.workflows.stats_flow import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    Stats,
)
from tcbot.utils.pagination import paginate

# ─────────────────────────── _paginate ──────────────────────────── #


def test_paginate_empty_list() -> None:
    chunk, total_pages, page = paginate([], 0, Stats.PAGE_SIZE)
    assert chunk == []
    assert total_pages == 1
    assert page == 0


def test_paginate_single_page() -> None:
    items = list(range(4))
    chunk, total_pages, page = paginate(items, 0, Stats.PAGE_SIZE)
    assert chunk == [0, 1, 2, 3]
    assert total_pages == 1
    assert page == 0


def test_paginate_multi_page_first() -> None:
    items = list(range(10))
    chunk, total_pages, page = paginate(items, 0, Stats.PAGE_SIZE)
    assert len(chunk) == Stats.PAGE_SIZE
    assert total_pages == 2
    assert page == 0


def test_paginate_multi_page_second() -> None:
    items = list(range(10))
    chunk, total_pages, page = paginate(items, 1, Stats.PAGE_SIZE)
    assert chunk == [6, 7, 8, 9]
    assert total_pages == 2
    assert page == 1


def test_paginate_clamps_out_of_bounds_page() -> None:
    items = list(range(6))
    chunk, total_pages, page = paginate(items, 99, Stats.PAGE_SIZE)
    assert total_pages == 1
    assert page == 0
    assert chunk == items


# ──────────────────────── Stats.main ────────────────────────────── #


async def test_stats_main_contains_community_name(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.users_roles, "get_owner_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        stats_flow.db.users_roles, "admin_count", AsyncMock(return_value=2)
    )
    monkeypatch.setattr(
        stats_flow.db.users_roles, "all_by_role", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        stats_flow.db.bans_db, "active_ban_count", AsyncMock(return_value=5)
    )
    monkeypatch.setattr(
        stats_flow.db.groups_db, "active_group_count", AsyncMock(return_value=3)
    )
    monkeypatch.setattr(
        stats_flow.db.users_cache, "total_users", AsyncMock(return_value=100)
    )

    text, kb = await Stats.main()

    assert "Staff" in text
    assert "5" in text  # active bans
    assert "3" in text  # connected chats
    assert kb is not None


# ─────────────────────── Stats.users_list ───────────────────────── #


async def test_stats_users_list_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.users_cache, "all_users", AsyncMock(return_value=[])
    )

    text, kb = await Stats.users_list(0)

    assert "No cached users" in text
    assert kb is not None


async def test_stats_users_list_with_users(monkeypatch) -> None:
    users = [
        {"user_id": 11, "first_name": "Alice", "username": None},
        {"user_id": 22, "first_name": "Bob", "username": "bob"},
    ]
    monkeypatch.setattr(
        stats_flow.db.users_cache, "all_users", AsyncMock(return_value=users)
    )

    text, kb = await Stats.users_list(0)

    assert "Alice" in text
    assert "Bob" in text
    assert "2 total" in text


# ──────────────────── Stats.user_detail ─────────────────────────── #


async def test_stats_user_detail_out_of_range(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.users_cache, "all_users", AsyncMock(return_value=[])
    )

    text, kb = await Stats.user_detail(0, 5)

    assert "not found" in text.lower()


async def test_stats_user_detail_valid(monkeypatch) -> None:
    users = [{"user_id": 11, "first_name": "Alice", "username": None, "last_name": "A"}]
    monkeypatch.setattr(
        stats_flow.db.users_cache, "all_users", AsyncMock(return_value=users)
    )

    text, kb = await Stats.user_detail(0, 0)

    assert "Alice" in text
    assert "11" in text


# ─────────────────── Stats.chats_list ───────────────────────────── #


async def test_stats_chats_list_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.groups_db, "active_groups", AsyncMock(return_value=[])
    )

    text, kb = await Stats.chats_list(0)

    assert "No connected groups" in text


async def test_stats_chats_list_with_groups(monkeypatch) -> None:
    groups = [{"chat_id": -1001, "title": "Main Chat"}]
    monkeypatch.setattr(
        stats_flow.db.groups_db, "active_groups", AsyncMock(return_value=groups)
    )

    text, kb = await Stats.chats_list(0)

    assert "Main Chat" in text
    assert "1 total" in text


# ─────────────────── Stats.bans_list ────────────────────────────── #


async def test_stats_bans_list_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.bans_db, "active_bans", AsyncMock(return_value=[])
    )

    text, kb = await Stats.bans_list(0)

    assert "No active" in text


async def test_stats_bans_list_with_bans(monkeypatch) -> None:
    bans = [{"banned_user_id": 99}]
    monkeypatch.setattr(
        stats_flow.db.bans_db, "active_bans", AsyncMock(return_value=bans)
    )
    monkeypatch.setattr(
        stats_flow.db.users_cache,
        "get_first_names_batch",
        AsyncMock(return_value={99: "Target"}),
    )

    text, kb = await Stats.bans_list(0)

    assert "Target" in text
    assert "1 total" in text


# ──────────────────── Stats.search_run ──────────────────────────── #


async def test_search_run_by_id_returns_matching_ban(monkeypatch) -> None:
    ban = {"banned_user_id": 42}
    monkeypatch.setattr(
        stats_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=ban)
    )

    result = await Stats.search_run("42")

    assert result == [ban]
    stats_flow.db.bans_db.get_active_ban.assert_awaited_once_with(42)


async def test_search_run_by_id_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.bans_db, "get_active_ban", AsyncMock(return_value=None)
    )

    result = await Stats.search_run("999")

    assert result == []


async def test_search_run_by_name_matches(monkeypatch) -> None:
    bans = [{"banned_user_id": 10}, {"banned_user_id": 20}]
    monkeypatch.setattr(
        stats_flow.db.bans_db, "active_bans", AsyncMock(return_value=bans)
    )
    monkeypatch.setattr(
        stats_flow.db.users_cache,
        "get_first_names_batch",
        AsyncMock(return_value={10: "Alice Smith", 20: "Bob Jones"}),
    )

    result = await Stats.search_run("alice")

    assert len(result) == 1
    assert result[0]["banned_user_id"] == 10


async def test_search_run_by_name_no_match(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.bans_db, "active_bans", AsyncMock(return_value=[])
    )

    result = await Stats.search_run("nobody")

    assert result == []


# ───────────────── Stats.search_results ─────────────────────────── #


async def test_search_results_empty(monkeypatch) -> None:
    text, kb = await Stats.search_results("foo", [])

    assert "No results" in text
    assert "foo" in text


async def test_search_results_with_hits(monkeypatch) -> None:
    results = [{"banned_user_id": 10}]
    monkeypatch.setattr(
        stats_flow.db.users_cache,
        "get_first_names_batch",
        AsyncMock(return_value={10: "Alice"}),
    )

    text, kb = await Stats.search_results("alice", results)

    assert "Alice" in text
    assert "1 found" in text


# ─────────────── Stats.open_search / clear_search ───────────────── #


def test_open_search_sets_user_data_keys() -> None:
    ctx = SimpleNamespace(user_data={})
    q = SimpleNamespace(message=SimpleNamespace(message_id=5, chat_id=-100))

    text, kb = Stats.open_search(ctx, q)

    assert ctx.user_data[SEARCH_KEY] is True
    assert ctx.user_data[MSG_KEY] == 5
    assert ctx.user_data[CHAT_KEY] == -100
    assert "Search" in text


def test_clear_search_removes_all_keys() -> None:
    ctx = SimpleNamespace(
        user_data={SEARCH_KEY: True, RESULTS_KEY: [], MSG_KEY: 1, CHAT_KEY: -100}
    )

    Stats.clear_search(ctx)

    for key in (SEARCH_KEY, RESULTS_KEY, MSG_KEY, CHAT_KEY):
        assert key not in ctx.user_data


# ─────────────────── Stats.staff_roster ─────────────────────────── #


async def test_staff_roster_no_owner_no_staff(monkeypatch) -> None:
    monkeypatch.setattr(
        stats_flow.db.users_roles, "get_owner_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        stats_flow.db.users_roles, "all_admins", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        stats_flow.db.users_roles, "all_by_role", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        stats_flow.db.users_cache,
        "get_mention_data_batch",
        AsyncMock(return_value={}),
    )

    text, kb = await Stats.staff_roster()

    assert "Staff Roster" in text
    assert "None assigned" in text
