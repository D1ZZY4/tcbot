# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Moderation expiry uses one clock for the decision and for its guard."""

from __future__ import annotations

from pathlib import Path

from tcbot.database.schema.loader import read_schema_file, split_statements


def test_the_insert_trigger_expires_prior_actions_on_the_database_clock() -> None:
    """The decision and the guard must agree on what 'expired' means."""
    statements = split_statements(read_schema_file("functions/moderation.sql"))
    prepare = next(
        statement
        for statement in statements
        if "FUNCTION %SCHEMA%.prepare_moderation_action" in statement
    )
    guard = next(
        statement
        for statement in statements
        if "FUNCTION %SCHEMA%.guard_moderation_action_update" in statement
    )

    assert "a.expires_at <= now()" in prepare
    assert "a.expires_at <= NEW.created_at" not in prepare
    # * A new decision still has to start before its own deadline.
    assert "NEW.expires_at <= NEW.created_at" in prepare
    assert "NEW.expires_at > now()" in guard


def test_a_new_head_revision_reapplies_the_schema() -> None:
    """Existing deployments receive the corrected function on upgrade."""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/0021_moderation_expiry_clock.py"
    )
    source = path.read_text(encoding="utf-8")

    assert 'revision: str = "0021_moderation_expiry_clock"' in source
    assert 'down_revision: str | None = "0020_erased_identity_guard"' in source
    assert "apply_schema(op.get_bind())" in source
