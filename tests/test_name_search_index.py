# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The member name search must stay indexable.

PostgreSQL cannot serve a case-insensitive match from an index, so the
search runs against the lowercase mirror columns with a case-sensitive
prefix query. The mirrors are written by the profile write, and the
indexes carry the pattern opclass that makes the prefix a range scan.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tcbot.database import engine as engine_module
from tcbot.database import users_cache
from tcbot.database.base import member_cache
from tests.postgres_support import (
    compile_sql,
    identity_db_call,
    literal_sql,
    stmt_params,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# * The two indexes that serve the prefix search.
_NAME_INDEXES: tuple[str, ...] = (
    "ix_member_cache_first_name_lower",
    "ix_member_cache_username_lower",
)


class _Recorder:
    """Captures the statements the member cache sends to the database."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows: list[dict[str, Any]] = []

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return 1

    async def fetch_all(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        return self.rows


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch the member cache transport so every statement is recorded."""
    rec = _Recorder()
    monkeypatch.setattr(users_cache, "db_call", identity_db_call)
    monkeypatch.setattr(users_cache, "run", rec.run)
    monkeypatch.setattr(users_cache, "fetch_all", rec.fetch_all)
    return rec


@pytest.fixture
async def postgres_members(postgres_db: str) -> AsyncIterator[None]:
    """Point the member cache at the test database with an empty table."""
    await engine_module.run(member_cache.delete())
    yield
    await engine_module.run(member_cache.delete())


# ─────────────────────────── Query shape ─────────────────────────── #


def test_the_search_uses_the_lowercase_mirrors(recorder: _Recorder) -> None:
    """The query must not use a case-insensitive match on the raw fields."""
    asyncio.run(users_cache.search_by_name("ali"))

    sql = compile_sql(recorder.statements[0])
    assert "member_cache.first_name_lower LIKE" in sql
    assert "member_cache.username_lower LIKE" in sql
    assert "member_cache.first_name LIKE" not in sql
    assert "member_cache.username LIKE" not in sql


def test_the_search_is_a_prefix_match(recorder: _Recorder) -> None:
    """The pattern anchors at the start: a name that contains the needle does not match."""
    asyncio.run(users_cache.search_by_name("ali"))

    sql = compile_sql(recorder.statements[0])
    assert "|| '%' ESCAPE" in sql
    assert "'%' ||" not in sql
    params = stmt_params(recorder.statements[0])
    assert params["first_name_lower_1"] == "ali"
    assert params["username_lower_1"] == "ali"


def test_the_search_lowercases_the_needle(recorder: _Recorder) -> None:
    """The caller may type any case: the needle is lowercased first."""
    asyncio.run(users_cache.search_by_name("BOB"))

    params = stmt_params(recorder.statements[0])
    assert params["first_name_lower_1"] == "bob"
    assert params["username_lower_1"] == "bob"


def test_the_search_treats_the_wildcards_literally(recorder: _Recorder) -> None:
    """A percent sign in the needle matches a percent sign, not anything."""
    asyncio.run(users_cache.search_by_name("a%b"))

    params = stmt_params(recorder.statements[0])
    assert params["first_name_lower_1"] == "a\\%b"


def test_the_search_is_capped(recorder: _Recorder) -> None:
    """The result limit keeps one search from scanning the whole cache."""
    asyncio.run(users_cache.search_by_name("ali", limit=3))

    params = stmt_params(recorder.statements[0])
    assert params["param_1"] == 3


# ──────────────────────────── Writes ─────────────────────────────── #


def test_the_write_populates_the_mirrors(recorder: _Recorder) -> None:
    """A profile write must carry the mirrors the search reads."""
    asyncio.run(users_cache.upsert_user(9, "Carol", "Carol", "Smith"))

    params = stmt_params(recorder.statements[0])
    assert params["user_id"] == 9
    assert params["first_name_lower"] == "carol"
    assert params["username_lower"] == "carol"


def test_a_partial_write_leaves_the_username_mirror_alone(
    recorder: _Recorder,
) -> None:
    """``username=None`` means "preserve", so the mirror must survive too."""
    asyncio.run(users_cache.upsert_user(9, "Carol", "Carol"))
    asyncio.run(users_cache.upsert_user(9, None, "Caroline"))

    params = stmt_params(recorder.statements[1])
    assert params["first_name_lower"] == "caroline"
    assert "username" not in params
    assert "username_lower" not in params
    sql = compile_sql(recorder.statements[1])
    assert "username" not in sql.split("ON CONFLICT")[1]


# ──────────────────────────── Indexes ────────────────────────────── #


def test_the_declared_indexes_use_the_pattern_opclass() -> None:
    """The prefix scan needs the pattern opclass under a real collation."""
    for name in _NAME_INDEXES:
        index = next(i for i in member_cache.indexes if i.name == name)
        ops = index.dialect_options["postgresql"]["ops"]
        assert "text_pattern_ops" in ops.values()


# ─────────────────────── Against a real server ───────────────────── #


async def test_the_search_matches_the_username_mirror(
    postgres_members: None,
) -> None:
    """A username prefix is found through its own mirror."""
    await users_cache.upsert_user(8, "Bobby", "Bob")

    found = await users_cache.search_by_name("BOB")

    assert [doc.get("user_id") for doc in found] == [8]


async def test_the_search_matches_the_first_name_mirror(
    postgres_members: None,
) -> None:
    """A first name prefix is found through its own mirror."""
    await users_cache.upsert_user(7, "Alice_1", "Alice")

    found = await users_cache.search_by_name("ali")

    assert [doc.get("user_id") for doc in found] == [7]


async def test_the_search_does_not_match_a_substring(
    postgres_members: None,
) -> None:
    """A name that only contains the needle is not a match."""
    await users_cache.upsert_user(7, "x_alice", "Bob")

    found = await users_cache.search_by_name("ali")

    assert found == []


async def test_the_search_is_served_by_the_index(postgres_members: None) -> None:
    """The prefix query runs on the index, not on a sequential scan."""
    rows = [
        {
            "user_id": index,
            "username": f"user{index}",
            "first_name": f"name{index}",
            "first_name_lower": f"name{index}",
            "username_lower": f"user{index}",
        }
        for index in range(1, 5001)
    ]
    await engine_module.run(
        member_cache.insert().values(
            [
                {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "first_name": row["first_name"],
                    "first_name_lower": row["first_name_lower"],
                    "username_lower": row["username_lower"],
                }
                for row in rows
            ]
        ),
    )
    await engine_module.run(text("ANALYZE member_cache"))

    plan = await engine_module.fetch_all(
        text(
            "EXPLAIN (COSTS OFF) SELECT user_id, first_name, username "
            "FROM member_cache WHERE first_name_lower LIKE 'name4999%' "
            "OR username_lower LIKE 'name4999%' LIMIT 5"
        )
    )
    plan_text = "\n".join(str(row["QUERY PLAN"]) for row in plan)

    assert "Seq Scan" not in plan_text
    assert "Index" in plan_text
    assert any(name in plan_text for name in _NAME_INDEXES)


async def test_the_live_index_carries_the_pattern_opclass(
    postgres_members: None,
) -> None:
    """The running database serves the prefix search from the pattern index."""
    rows = await engine_module.fetch_all(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'member_cache'"
        )
    )
    definitions = {str(row["indexname"]): str(row["indexdef"]) for row in rows}

    for name in _NAME_INDEXES:
        assert name in definitions
        assert "text_pattern_ops" in definitions[name]


async def test_the_partial_write_keeps_the_stored_username(
    postgres_members: None,
) -> None:
    """A partial write leaves the stored username and its mirror alone."""
    await users_cache.upsert_user(9, "Carol", "Carol")
    await users_cache.upsert_user(9, None, "Caroline")

    stored = await users_cache.get_user(9)
    assert stored is not None
    assert stored.get("username") == "Carol"
    assert stored.get("first_name") == "Caroline"
    found = await users_cache.search_by_name("carol")
    assert [doc.get("user_id") for doc in found] == [9]


def test_the_literal_sql_keeps_the_prefix_pattern() -> None:
    """The rendered statement shows the prefix pattern, not a substring one."""
    stmt = member_cache.select().where(
        member_cache.c.first_name_lower.startswith("ali", escape="\\", autoescape=True)
    )
    sql = literal_sql(stmt)

    assert "|| '%' ESCAPE" in sql
    assert "'%' ||" not in sql
