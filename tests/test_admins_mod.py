# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Behavioural tests for :mod:`tgbot_tcf.modules.admins_mod`.

The DB layer is stubbed so the tests run without MongoDB. The intent is to
pin the call sequence each business-logic helper performs against the
repositories.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from tgbot_tcf.modules import admins_mod


@pytest.fixture
def fake_admins_repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = {
        "add_admin": AsyncMock(),
        "remove_admin": AsyncMock(return_value=True),
        "is_admin": AsyncMock(return_value=False),
        "replace_owner": AsyncMock(),
        "upsert_admin_if_missing": AsyncMock(),
    }
    for name, mock in fakes.items():
        monkeypatch.setattr(admins_mod.admins_repo, name, mock)
    return fakes


@pytest.fixture
def fake_requests_repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = {
        "create": AsyncMock(),
        "find_by_id": AsyncMock(),
        "list_pending": AsyncMock(return_value=[]),
        "resolve": AsyncMock(),
    }
    for name, mock in fakes.items():
        monkeypatch.setattr(admins_mod.requests_repo, name, mock)
    return fakes


async def test_promote_immediately_calls_add_admin(
    fake_admins_repo: dict[str, AsyncMock],
) -> None:
    await admins_mod.promote_immediately(target_id=42, by_owner_id=1)
    fake_admins_repo["add_admin"].assert_awaited_once()
    kwargs = fake_admins_repo["add_admin"].call_args.kwargs
    assert kwargs["user_id"] == 42
    assert kwargs["promoted_by"] == 1
    assert isinstance(kwargs["promoted_date"], datetime)


async def test_create_promotion_request_returns_uuid_and_persists(
    fake_requests_repo: dict[str, AsyncMock],
) -> None:
    request_id = await admins_mod.create_promotion_request(
        target_id=42, requested_by=1
    )
    assert isinstance(request_id, str) and len(request_id) >= 32
    fake_requests_repo["create"].assert_awaited_once()


async def test_approve_request_skips_when_not_pending(
    fake_admins_repo: dict[str, AsyncMock],
    fake_requests_repo: dict[str, AsyncMock],
) -> None:
    fake_requests_repo["find_by_id"].return_value = {
        "request_id": "r",
        "target_id": 42,
        "status": "approved",
    }
    out = await admins_mod.approve_request(request_id="r", by_owner_id=1)
    assert out is None
    fake_admins_repo["add_admin"].assert_not_awaited()
    fake_requests_repo["resolve"].assert_not_awaited()


async def test_approve_request_promotes_only_when_not_admin(
    fake_admins_repo: dict[str, AsyncMock],
    fake_requests_repo: dict[str, AsyncMock],
) -> None:
    fake_requests_repo["find_by_id"].return_value = {
        "request_id": "r",
        "target_id": 42,
        "status": "pending",
    }
    fake_admins_repo["is_admin"].return_value = False
    out = await admins_mod.approve_request(request_id="r", by_owner_id=1)
    assert out is not None
    fake_admins_repo["add_admin"].assert_awaited_once()
    fake_requests_repo["resolve"].assert_awaited_once()


async def test_approve_request_idempotent_when_already_admin(
    fake_admins_repo: dict[str, AsyncMock],
    fake_requests_repo: dict[str, AsyncMock],
) -> None:
    fake_requests_repo["find_by_id"].return_value = {
        "request_id": "r",
        "target_id": 42,
        "status": "pending",
    }
    fake_admins_repo["is_admin"].return_value = True
    await admins_mod.approve_request(request_id="r", by_owner_id=1)
    fake_admins_repo["add_admin"].assert_not_awaited()
    fake_requests_repo["resolve"].assert_awaited_once()


async def test_reject_request_resolves_when_pending(
    fake_requests_repo: dict[str, AsyncMock],
) -> None:
    fake_requests_repo["find_by_id"].return_value = {
        "request_id": "r",
        "status": "pending",
    }
    out = await admins_mod.reject_request(request_id="r", by_owner_id=1)
    assert out is not None
    fake_requests_repo["resolve"].assert_awaited_once()
    kwargs = fake_requests_repo["resolve"].call_args.kwargs
    assert kwargs["status"] == "rejected"


async def test_demote_user_returns_repo_result(
    fake_admins_repo: dict[str, AsyncMock],
) -> None:
    fake_admins_repo["remove_admin"].return_value = True
    assert await admins_mod.demote_user(42) is True
    fake_admins_repo["remove_admin"].return_value = False
    assert await admins_mod.demote_user(42) is False


async def test_transfer_ownership_swaps_roles(
    fake_admins_repo: dict[str, AsyncMock],
) -> None:
    await admins_mod.transfer_ownership(new_owner_id=2, old_owner_id=1)
    fake_admins_repo["replace_owner"].assert_awaited_once_with(2)
    fake_admins_repo["remove_admin"].assert_awaited_once_with(2)
    fake_admins_repo["upsert_admin_if_missing"].assert_awaited_once()
    kwargs = fake_admins_repo["upsert_admin_if_missing"].call_args.kwargs
    assert kwargs["user_id"] == 1
