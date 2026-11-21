# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Schema setup must recover from a run that stopped before teardown."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text

from tests.postgres_support import (
    configured_database_url,
    create_empty_schema,
    drop_schema,
    sync_database_url,
    worker_schema,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.postgres]

_SCHEMA: str = worker_schema("tcbot_schema_helper_check")


@pytest.fixture
def leftover_schema() -> Iterator[str]:
    """Leave a populated schema behind, then remove it after the test."""
    url = configured_database_url()
    if url is None:
        pytest.skip("TCBOT_TEST_DATABASE_URL is not set; skipping the schema check.")
    engine = create_engine(sync_database_url(url), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{_SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{_SCHEMA}"'))
            conn.execute(
                text(f'CREATE TABLE "{_SCHEMA}".leftover (id integer primary key)')
            )
            conn.execute(text(f'INSERT INTO "{_SCHEMA}".leftover VALUES (1)'))
    finally:
        engine.dispose()
    try:
        yield _SCHEMA
    finally:
        drop_schema(url, _SCHEMA)


def test_create_empty_schema_clears_a_leftover_schema(leftover_schema: str) -> None:
    """A stale schema is replaced, not reused by the next migration run."""
    url = configured_database_url()
    if url is None:
        pytest.skip("TCBOT_TEST_DATABASE_URL is not set; skipping the schema check.")
    create_empty_schema(url, leftover_schema)

    engine = create_engine(sync_database_url(url), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            tables = (
                conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": leftover_schema},
                )
                .scalars()
                .all()
            )
            exists = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
                    "WHERE schema_name = :schema)"
                ),
                {"schema": leftover_schema},
            ).scalar()
    finally:
        engine.dispose()

    assert exists is True
    assert tables == []
