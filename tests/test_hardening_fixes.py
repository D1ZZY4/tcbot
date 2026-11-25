# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for the evidence-driven hardening and bug-fix batch."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot import cfg
from tcbot.database import enforcement_ledger
from tcbot.database.rules_db import sets as rules_sets
from tcbot.database.rules_db.categories import _available_key
from tcbot.database.schema import SCHEMA_FILES, _schema_of
from tcbot.database.schema.loader import file_statements
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest
from tcbot.modules.helper.rich.edit import _edit_via
from tests.postgres_support import identity_db_call


def test_non_ascii_category_slug_collision_stays_valid() -> None:
    """A title with no ASCII alphanumerics must not produce an invalid '-2' key."""
    assert _available_key("中文分类", {"category"}) == "category-2"
    assert _available_key("!!!", {"category", "category-2"}) == "category-3"
    assert _available_key("News", set()) == "news"


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


async def test_existing_rule_set_without_categories_is_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy set with no catalogue gets its defaults before items are read."""
    seeded: list[int] = []

    async def _one(stmt: Any) -> dict[str, Any]:
        return {"id": 7, "scope_type": "community"}

    async def _none(stmt: Any) -> list[dict[str, Any]]:
        return []

    async def _seed(sess: Any, set_id: int, now: Any) -> None:
        seeded.append(set_id)

    async def _transaction(op: Any) -> Any:
        return await op(object())

    monkeypatch.setattr(rules_sets, "db_call", identity_db_call)
    monkeypatch.setattr(rules_sets, "fetch_one", _one)
    monkeypatch.setattr(rules_sets, "fetch_all", _none)
    monkeypatch.setattr(rules_sets, "run_transaction", _transaction)
    monkeypatch.setattr(rules_sets, "_seed_default_categories", _seed)

    rule_set = await rules_sets.get_or_create_community_set()

    assert rule_set["id"] == 7
    assert seeded == [7]
