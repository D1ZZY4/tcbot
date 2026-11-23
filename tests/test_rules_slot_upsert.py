# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules channel slots conflict on the expression index, not a constraint name."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from tcbot.database.rules_db import publications


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
