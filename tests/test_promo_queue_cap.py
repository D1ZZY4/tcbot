# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion-queue list shows a cap notice when the backlog exceeds the 200-row cap."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from tcbot import database as db
from tcbot.database import queues_db
from tcbot.modules import admins
from tcbot.utils.i18n import t
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def promo_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty promotion-queue table."""
    await reset_community()
    await seed_users(1, 2, 3, 9)
    yield postgres_db
    await reset_community()


async def test_pending_count_counts_only_the_pending_rows(promo_db: str) -> None:
    """The count helper filters on the pending status."""
    await queues_db.enqueue(1, None, "One", 9)
    await queues_db.enqueue(2, None, "Two", 9)
    await queues_db.resolve(await queues_db.enqueue(3, None, "Three", 9), "rejected", 9)

    assert await queues_db.pending_count() == 2


def _rows(n: int = 200) -> list[dict[str, Any]]:
    return [
        {
            "target_user_id": i,
            "first_name": f"U{i}",
            "username": None,
            "request_id": f"r{i}",
        }
        for i in range(n)
    ]


def _set_up(
    monkeypatch: pytest.MonkeyPatch,
    total_pending: int,
) -> list[str]:
    captured: list[str] = []

    async def _locale(*args: Any, **kwargs: Any) -> str:
        return "en-US"

    async def _all_pending(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return _rows()

    async def _pending_count(*args: Any, **kwargs: Any) -> int:
        return total_pending

    async def _owner(*args: Any, **kwargs: Any) -> int:
        return 1

    async def _role(*args: Any, **kwargs: Any) -> str:
        return "founder"

    async def _safe_reply(_msg: Any, text: str, **kwargs: Any) -> None:
        captured.append(text)

    monkeypatch.setattr(admins, "locale_for_update", _locale)
    monkeypatch.setattr(db.queues_db, "all_pending", _all_pending)
    monkeypatch.setattr(db.queues_db, "pending_count", _pending_count)
    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(admins, "safe_reply", _safe_reply)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(),
        effective_user=SimpleNamespace(id=1),
    )
    asyncio.run(
        admins.cmd_promote_list(  # type: ignore[arg-type]
            update,
            SimpleNamespace(),  # type: ignore[arg-type]
        )
    )
    return captured


def test_promote_list_appends_cap_notice_when_backlog_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _set_up(monkeypatch, total_pending=234)

    assert len(captured) == 1
    notice = t("admins.list.cap_notice", "en-US", shown=200, total=234)
    assert notice in captured[0]


def test_promote_list_header_shows_true_total_when_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _set_up(monkeypatch, total_pending=234)

    assert len(captured) == 1
    assert "Pending Promotion Requests \\(234\\)" in captured[0]


def test_promote_list_omits_cap_notice_within_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _set_up(monkeypatch, total_pending=200)

    assert len(captured) == 1
    assert "Showing the" not in captured[0]
