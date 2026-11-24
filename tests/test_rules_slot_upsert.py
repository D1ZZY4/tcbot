# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules channel slots conflict on the expression index, not a constraint name."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from tcbot import database as db
from tcbot.database.rules_db import publications
from tests.postgres_support import seed_users
from tests.test_rules_domain import rules_ready  # noqa: F401


def test_slot_upsert_targets_the_expression_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain unique index cannot be an ON CONFLICT constraint target.

    The slot index coalesces the nullable thread id, so the conflict target
    has to repeat that expression. Naming the index with ON CONSTRAINT is
    rejected by PostgreSQL and would stop every rules publish after the
    version was already promoted.
    """

    async def _db_call(op: Any, **kwargs: Any) -> Any:
        return await op()

    captured: list[Any] = []

    async def _fetch_all(stmt: Any) -> list[dict[str, Any]]:
        captured.append(stmt)
        return [{"id": 1}]

    monkeypatch.setattr(publications, "db_call", _db_call)
    monkeypatch.setattr(publications, "fetch_all", _fetch_all)

    asyncio.run(
        publications.upsert_slot(
            set_id=1,
            version_id=2,
            locale="en-US",
            chat_id=-100,
            message_thread_id=None,
            category_key="cheat",
            part_index=0,
            content_hash="abc",
            run_id=3,
        )
    )

    assert len(captured) == 1
    sql = str(captured[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (" in sql
    assert "ON CONSTRAINT" not in sql
    assert "coalesce(message_thread_id" in sql


def test_retire_unused_is_scoped_to_the_published_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishing one locale must not retire the other locale's live slots."""

    async def _db_call(op: Any, **kwargs: Any) -> Any:
        return await op()

    captured: list[Any] = []

    async def _run(stmt: Any) -> int:
        captured.append(stmt)
        return 0

    monkeypatch.setattr(publications, "db_call", _db_call)
    monkeypatch.setattr(publications, "run", _run)

    asyncio.run(publications.retire_unused(1, "id-ID", [7]))

    sql = str(captured[0].compile(dialect=postgresql.dialect()))
    assert "locale =" in sql
    assert "id NOT IN" in sql
    params = [str(value) for value in captured[0].compile().params.values()]
    assert "id-ID" in params


@pytest.mark.usefixtures("rules_ready")
async def test_slot_upsert_updates_one_row_on_postgres() -> None:
    """A second upsert reuses the slot instead of targeting a missing constraint."""
    await seed_users(7)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    version = await db.rules_db.open_draft(set_id, 7)
    version_id = int(version["id"])
    run_id = await db.rules_db.runs.acquire(set_id, version_id, -100)

    common = {
        "set_id": set_id,
        "version_id": version_id,
        "locale": "en-US",
        "chat_id": -100,
        "message_thread_id": None,
        "category_key": "cheat",
        "part_index": 0,
        "run_id": run_id,
    }
    first = await publications.upsert_slot(content_hash="abc", **common)
    second = await publications.upsert_slot(content_hash="def", **common)
    assert int(second["id"]) == int(first["id"])
    assert str(second["content_hash"]) == "def"
