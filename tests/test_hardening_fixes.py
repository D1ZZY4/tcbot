# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for the evidence-driven hardening and bug-fix batch."""

from __future__ import annotations

from typing import Any

import pytest
from pyrogram.errors import MessageIdInvalid, MessageNotModified

from tcbot import cfg
from tcbot.database import enforcement_ledger
from tcbot.database.schema import SCHEMA_FILES, _schema_of
from tcbot.database.schema.loader import file_statements
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest
from tcbot.modules.helper.rich.edit_msg import _edit_via


def test_schema_placeholder_is_valid_inside_sql_literals() -> None:
    """The schema resolved from the search path must fit SQL literals."""

    class _Scalar:
        def __init__(self, value: str) -> None:
            self._value = value

        def scalar(self) -> str:
            return self._value

    class _Connection:
        def exec_driver_sql(self, sql: str) -> _Scalar:
            return _Scalar('"public", extensions' if "search_path" in sql else "public")

    schema = _schema_of(_Connection())  # type: ignore[arg-type]
    assert schema == "public"
    statements = [
        statement
        for name in SCHEMA_FILES
        if name.startswith("functions/")
        for statement in file_statements(name, schema)
    ]
    script = "\n".join(statements)
    assert "SET search_path TO 'pg_catalog', 'public'" in script
    assert "'\"public\"'" not in script


async def test_edit_via_reports_missing_message() -> None:
    """A swallowed 'not found' must be observable so a fresh post can be sent."""

    async def ok() -> None:
        return None

    async def gone() -> None:
        raise BadRequest("Message to edit not found")

    async def unchanged() -> None:
        raise BadRequest("Message is not modified")

    assert await _edit_via(
        ok(), log_level="debug", log_label=None, catch_all=False, default_msg="x"
    )
    assert not await _edit_via(
        gone(), log_level="debug", log_label=None, catch_all=False, default_msg="x"
    )
    assert await _edit_via(
        unchanged(), log_level="debug", log_label=None, catch_all=False, default_msg="x"
    )


async def test_edit_via_recognizes_real_kurigram_refusals() -> None:
    """A real RPC no-op is swallowed and a dead message reports as gone."""

    async def not_modified() -> None:
        raise MessageNotModified()

    async def dead_message() -> None:
        raise MessageIdInvalid()

    assert await _edit_via(
        not_modified(),
        log_level="debug",
        log_label=None,
        catch_all=False,
        default_msg="x",
    )
    assert not await _edit_via(
        dead_message(),
        log_level="debug",
        log_label=None,
        catch_all=False,
        default_msg="x",
    )


async def test_primary_group_keeps_enforcement_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inactive main group keeps the same retry path as active groups."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Result:
        def mappings(self) -> _Result:
            return self

        def all(self) -> list[dict[str, Any]]:
            return []

        def __iter__(self) -> Any:
            return iter(())

    class _Session:
        async def execute(
            self, stmt: Any, params: dict[str, Any] | None = None
        ) -> _Result:
            calls.append((str(stmt), params or {}))
            return _Result()

    async def _transaction(op: Any) -> Any:
        return await op(_Session())

    monkeypatch.setattr(enforcement_ledger, "run_transaction", _transaction)

    await enforcement_ledger.claim_targets(1)
    await enforcement_ledger.requeue_stale_runs()

    claim, requeue = calls[0], calls[-1]
    assert "cc.chat_id = :primary_chat_id" in claim[0]
    assert claim[1]["primary_chat_id"] == cfg.main_group
    assert "cc.chat_id = :primary_chat_id" in requeue[0]
    assert requeue[1]["primary_chat_id"] == cfg.main_group


async def test_run_action_claimable_marker_matches_the_retry_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The demote guard must not treat a pending target as unclaimable.

    ``claim_targets`` requires a live chat only for a failed retry; a pending
    target is claimed unconditionally. The projection that feeds the demote
    gate must use the same rule, or a staffer can be stripped without being
    enforced while a pending target is still delivered.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Result:
        def mappings(self) -> _Result:
            return self

        def first(self) -> None:
            return None

        def all(self) -> list[dict[str, Any]]:
            return []

        def __iter__(self) -> Any:
            return iter(())

    class _Session:
        async def execute(
            self, stmt: Any, params: dict[str, Any] | None = None
        ) -> _Result:
            calls.append((str(stmt), params or {}))
            return _Result()

    async def _transaction(op: Any) -> Any:
        return await op(_Session())

    monkeypatch.setattr(enforcement_ledger, "run_transaction", _transaction)

    assert await enforcement_ledger.load_run_action(1) is None
    sql, params = calls[0]
    compact = " ".join(sql.split())
    assert "AS has_claimable_target" in compact
    assert (
        "t.status = 'failed' AND t.next_retry_at IS NOT NULL "
        "AND t.next_retry_at <= now() AND EXISTS ( SELECT 1 "
        "FROM connected_chats AS cc"
    ) in compact
    assert params["primary_chat_id"] == cfg.main_group
