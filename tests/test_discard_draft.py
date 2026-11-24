# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Discarding a draft removes its items before its version, atomically."""

from __future__ import annotations

import asyncio
from typing import Any

from tcbot.database.rules_db import drafts


def test_discard_draft_deletes_items_before_the_version() -> None:
    """A draft with items can be discarded without an FK violation."""
    executed: list[str] = []

    class _Result:
        def first(self) -> tuple[int] | None:
            return (7,)

        @property
        def rowcount(self) -> int:
            return 1

    class _Session:
        async def execute(self, statement: Any) -> _Result:
            text = str(statement)
            executed.append(text)
            return _Result()

    async def _transaction(op: Any) -> bool:
        return await op(_Session())

    original = drafts.run_transaction
    drafts.run_transaction = _transaction  # type: ignore[assignment]
    try:
        assert asyncio.run(drafts.discard_draft(7)) is True
    finally:
        drafts.run_transaction = original  # type: ignore[assignment]

    assert len(executed) == 3
    assert "SELECT" in executed[0]
    assert "DELETE FROM rule_items" in executed[1]
    assert "DELETE FROM rule_set_versions" in executed[2]
