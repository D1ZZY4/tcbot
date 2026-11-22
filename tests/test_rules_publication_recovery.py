# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A deleted channel message must be re-sent, not edited forever."""

from __future__ import annotations

import asyncio
from typing import Any

from tcbot.database.rules_db import publications


def test_mark_failed_missing_clears_the_message_id(monkeypatch: Any) -> None:
    """A missing message drops its stale id so publish takes the send branch."""

    async def _fake_db_call(factory: Any) -> Any:
        await factory()
        return None

    monkeypatch.setattr(publications, "db_call", _fake_db_call)

    # Inspect the built statement directly by capturing it through `run`.
    statements: list[Any] = []

    async def _fake_run(stmt: Any) -> None:
        statements.append(stmt)

    monkeypatch.setattr(publications, "run", _fake_run)
    asyncio.run(publications.mark_failed(7, "message not found", missing=True))

    compiled = statements[0].compile()
    assert compiled.params["message_id"] is None
    assert compiled.params["status"] == "missing"


def test_mark_failed_transient_keeps_the_message_id(monkeypatch: Any) -> None:
    """A transient failure keeps the id so publish can retry the edit."""
    statements: list[Any] = []

    async def _fake_db_call(factory: Any) -> Any:
        await factory()
        return None

    async def _fake_run(stmt: Any) -> None:
        statements.append(stmt)

    monkeypatch.setattr(publications, "db_call", _fake_db_call)
    monkeypatch.setattr(publications, "run", _fake_run)

    asyncio.run(publications.mark_failed(7, "flood wait"))

    compiled = statements[0].compile()
    assert "message_id" not in compiled.params
    assert compiled.params["status"] == "failed"
