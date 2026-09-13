# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Server-side pagination of /check drill-downs (skip/limit + exact total)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import check_flow


async def _fake_name(uid: int) -> str:
    return "Alice"


async def _no_names(ids: list[int]) -> dict[int, str]:
    return {}


async def _group_titles(ids: list[int]) -> dict[int, str]:
    return {22: "Group"}


def _ban_doc(ban_id: str) -> dict[str, Any]:
    return {
        "is_active": True,
        "ban_id": ban_id,
        "timestamp": None,
        "reason": "spam",
    }


class _SliceDB:
    """Records the skip/limit each listing helper receives and serves slices."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[int, int, int | None]] = []

    async def fetch(
        self, user_id: int, *, skip: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((user_id, skip, limit))
        if limit is None:
            return self.rows
        return self.rows[skip : skip + limit]


def test_ban_list_render_passes_skip_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _SliceDB([_ban_doc(f"b{i}") for i in range(1, 24)])

    async def _count(user_id: int) -> int:
        return 23

    monkeypatch.setattr(check_flow, "_name", _fake_name)
    monkeypatch.setattr(db.bans_db, "user_bans", fake_db.fetch)
    monkeypatch.setattr(db.bans_db, "user_ban_count", _count)

    text, _markup = asyncio.run(check_flow.Check.bans_list(42, 2, None))
    assert fake_db.calls == [(42, 10, 5)]
    assert "23 total" in text
    assert "page 3/5" in text


def test_ban_list_render_clamps_out_of_range_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _SliceDB([_ban_doc(f"b{i}") for i in range(1, 4)])

    async def _count(user_id: int) -> int:
        return 3

    monkeypatch.setattr(check_flow, "_name", _fake_name)
    monkeypatch.setattr(db.bans_db, "user_bans", fake_db.fetch)
    monkeypatch.setattr(db.bans_db, "user_ban_count", _count)

    text, _markup = asyncio.run(check_flow.Check.bans_list(42, 99, None))
    assert fake_db.calls == [(42, 0, 5)]
    assert "3 total" in text
    assert "page 1/1" in text


def test_ban_list_render_count_fail_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _SliceDB([_ban_doc("b1"), _ban_doc("b2")])

    async def _boom(user_id: int) -> int:
        raise RuntimeError("count down")

    monkeypatch.setattr(check_flow, "_name", _fake_name)
    monkeypatch.setattr(db.bans_db, "user_bans", fake_db.fetch)
    monkeypatch.setattr(db.bans_db, "user_ban_count", _boom)

    text, _markup = asyncio.run(check_flow.Check.bans_list(42, 0, None))
    assert fake_db.calls == [(42, 0, 5)]
    assert "2 total" in text


def test_warns_in_group_uses_server_side_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "timestamp": None,
            "admin_id": 1,
            "reason": f"r{i}",
            "user_id": 42,
            "chat_id": 22,
        }
        for i in range(1, 9)
    ]
    calls: list[tuple[int, int, int, int | None]] = []

    async def _get_warns(
        user_id: int, chat_id: int, *, skip: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        calls.append((user_id, chat_id, skip, limit))
        if limit is None:
            return rows
        return rows[skip : skip + limit]

    async def _count(user_id: int, chat_id: int) -> int:
        return 8

    monkeypatch.setattr(check_flow, "_name", _fake_name)
    monkeypatch.setattr(db.warns_db, "warn_count", _count)
    monkeypatch.setattr(db.warns_db, "get_warns", _get_warns)
    monkeypatch.setattr(db.groups_db, "get_group_titles", _group_titles)
    monkeypatch.setattr(db.users_cache, "get_first_names_batch", _no_names)

    text, _markup = asyncio.run(check_flow.Check.warns_in_group(42, 22, 1, None))
    assert calls == [(42, 22, 5, 5)]
    assert "8 total" in text
    assert "page 2/2" in text
    assert text.index("r8") < text.index("r7") < text.index("r6")
