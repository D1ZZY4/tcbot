# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Pending promotion requests expire instead of blocking the queue forever."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from tcbot.database import engine as engine_module
from tcbot.database import queues_db
from tcbot.database.base import promotion_requests
from tcbot.utils.time_and_date import utc_now
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def queue_db(postgres_db: str) -> AsyncIterator[str]:
    await reset_community()
    await seed_users(7, 42)
    yield postgres_db
    await reset_community()


async def test_a_pending_request_carries_its_expiry(queue_db: str) -> None:
    request_id = await queues_db.enqueue(42, "target", "Target", 7)

    row = await engine_module.fetch_one(
        select(
            promotion_requests.c.status,
            promotion_requests.c.expires_at,
        ).where(promotion_requests.c.request_id == request_id)
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["expires_at"] is not None


async def test_expiry_frees_the_pending_slot(queue_db: str) -> None:
    first = await queues_db.enqueue(42, "target", "Target", 7)
    await engine_module.run(
        promotion_requests.update()
        .where(promotion_requests.c.request_id == first)
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )

    assert await queues_db.get_request(42) is None
    assert await queues_db.resolve(first, "approved", 7) is False
    assert await queues_db.expire_stale_requests() == 1

    row = await engine_module.fetch_one(
        select(promotion_requests.c.status).where(
            promotion_requests.c.request_id == first
        )
    )
    assert row == {"status": "expired"}

    second = await queues_db.enqueue(42, "target", "Target", 7)
    assert second != first
    assert await queues_db.get_request(42) is not None
