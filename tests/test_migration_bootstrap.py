# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A schema bootstrapped outside Alembic must still boot the bot.

A database created from the declared metadata carries every table but no
``alembic_version`` row, so the first migration would try to create the
tables again and the bot would crash-loop on boot with a duplicate-table
error. The migration environment stamps the base revision in that case
and lets the normal upgrade apply everything after it.

A database that is empty, or that carries only part of the schema, must
not be stamped: a partial schema has to fail loudly in the migration.
"""

from __future__ import annotations

from typing import Any

import pytest

from tcbot.database import migrations
from tcbot.database.base import metadata


class _FakeMigrationContext:
    """Migration-context double recording the stamp."""

    def __init__(self, heads: tuple[str, ...]) -> None:
        self._heads = heads
        self.stamped: list[str] = []

    def get_current_heads(self) -> tuple[str, ...]:
        return self._heads

    def stamp(self, scripts: Any, revision: str) -> None:
        self.stamped.append(revision)


class _FakeScripts:
    """Script-directory double exposing the base revision."""

    def get_base(self) -> str:
        return "0001_initial"


def _patch_inspector(monkeypatch: pytest.MonkeyPatch, tables: set[str]) -> None:
    class _Inspector:
        def get_table_names(self) -> list[str]:
            return sorted(tables)

    monkeypatch.setattr(migrations, "inspect", lambda _connection: _Inspector())


def _declared() -> set[str]:
    return set(metadata.tables)


def test_a_bootstrapped_schema_is_stamped_at_the_base_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every declared table present and no version row: stamp and upgrade."""
    _patch_inspector(monkeypatch, _declared())
    context = _FakeMigrationContext(heads=())

    migrations.stamp_bootstrap_schema(context, object(), _FakeScripts())  # type: ignore[arg-type]

    assert context.stamped == ["0001_initial"]


def test_a_stamped_database_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A version row means the migration owns the schema."""
    _patch_inspector(monkeypatch, _declared())
    context = _FakeMigrationContext(heads=("0002",))

    migrations.stamp_bootstrap_schema(context, object(), _FakeScripts())  # type: ignore[arg-type]

    assert context.stamped == []


def test_a_partial_schema_is_not_stamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A half-built schema must fail in the migration, not be stamped."""
    declared = _declared()
    _patch_inspector(monkeypatch, declared - {"bans"})
    context = _FakeMigrationContext(heads=())

    migrations.stamp_bootstrap_schema(context, object(), _FakeScripts())  # type: ignore[arg-type]

    assert context.stamped == []


def test_an_empty_database_is_not_stamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty database is the normal fresh-deployment case."""
    _patch_inspector(monkeypatch, set())
    context = _FakeMigrationContext(heads=())

    migrations.stamp_bootstrap_schema(context, object(), _FakeScripts())  # type: ignore[arg-type]

    assert context.stamped == []
