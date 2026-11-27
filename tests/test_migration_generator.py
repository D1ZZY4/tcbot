# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The bootstrap generator keeps first-revision DDL aligned with metadata."""

from __future__ import annotations

import ast

import sqlalchemy as sa

from scripts import generate_initial_migration as generator
from tcbot.database.base import metadata


def test_generated_migration_is_valid_python() -> None:
    """A generated revision must at least parse before it can be applied."""
    ast.parse(generator.render())


def test_generated_migration_imports_without_unresolved_type_names() -> None:
    """ast.parse accepts sa.JSONB; executing the source does not."""
    source = generator.render()
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated migration>", "exec"), namespace)

    assert namespace["revision"] == "0001_initial"
    assert "postgresql.JSONB(" in source
    assert "sa.Text()" in source


def test_every_metadata_constraint_and_column_kind_is_rendered() -> None:
    """The old renderer silently dropped referential integrity and checks."""
    source = generator.render()
    foreign_keys = sum(
        len(table.foreign_key_constraints) for table in metadata.tables.values()
    )
    checks = sum(
        1
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    )
    identities = sum(
        1
        for table in metadata.tables.values()
        for column in table.columns
        if column.identity is not None
    )
    computed = sum(
        1
        for table in metadata.tables.values()
        for column in table.columns
        if column.computed is not None
    )

    assert source.count("sa.ForeignKeyConstraint(") == foreign_keys
    assert source.count("sa.CheckConstraint(") == checks
    assert source.count("sa.Identity(") == identities
    assert source.count("sa.Computed(") == computed
    assert foreign_keys > 0 and checks > 0 and identities > 0


def test_the_deferred_composite_foreign_key_keeps_its_options() -> None:
    """A deferred composite key loses its meaning if options are dropped."""
    source = generator.render()

    assert "fk_moderation_evidence_items_upload_destination" in source
    assert "'moderation_evidence_uploads.id'" in source
    assert "'moderation_evidence_uploads.destination_chat_id'" in source
    assert "deferrable=True" in source
    assert "initially='DEFERRED'" in source
