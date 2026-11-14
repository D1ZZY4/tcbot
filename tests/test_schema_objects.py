# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Schema object application: trigger drops match the tables that exist."""

from __future__ import annotations

from tcbot.database.schema import _drop_statements


def test_trigger_drops_use_the_unqualified_table_name() -> None:
    """A schema-qualified trigger target still matches an existing table.

    ``_existing_tables`` reports bare table names, so a drop statement built
    from the qualified name would never match and the next apply would fail
    on a duplicate trigger.
    """
    statements = _drop_statements(
        "triggers.sql",
        '"test"',
        {"moderation_actions"},
    )

    assert any(
        "DROP TRIGGER IF EXISTS assign_moderation_action_external_ref" in statement
        for statement in statements
    )
    assert all('ON "test".moderation_actions' in statement for statement in statements)


def test_trigger_drops_skip_tables_that_do_not_exist() -> None:
    """A schema without the base tables yields no drop statements."""
    assert _drop_statements("triggers.sql", '"test"', set()) == []
