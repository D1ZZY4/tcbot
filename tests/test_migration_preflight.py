# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Schema compatibility checks for the legacy Alembic migration path."""

from __future__ import annotations

import pytest

from tcbot.database.migrations import validate_schema_relations


def test_empty_schema_is_valid_for_initial_migration() -> None:
    """A new, empty application schema can receive the initial revision."""
    validate_schema_relations(set())


def test_versioned_legacy_schema_is_not_rejected() -> None:
    """An existing database with Alembic history remains eligible for upgrade."""
    validate_schema_relations({"alembic_version", "bans", "tc_owners"})


def test_scheduler_only_schema_is_not_treated_as_application_schema() -> None:
    """The APScheduler-owned job table may exist outside application metadata."""
    validate_schema_relations({"apscheduler_jobs"})


@pytest.mark.parametrize(
    "relation",
    [
        "audit_events",
        "chat_members",
        "chat_settings",
        "federation_groups",
        "federation_settings",
        "federations",
        "join_requests",
        "moderation_actions",
        "moderation_appeals",
        "moderation_case_rules",
        "moderation_cases",
        "moderation_evidence_items",
        "moderation_evidence_uploads",
        "moderation_messages",
        "permission_definitions",
        "role_assignments",
        "role_definitions",
        "role_permissions",
        "rule_acknowledgements",
        "rule_items",
        "rule_set_versions",
        "rule_sets",
        "telegram_chats",
        "telegram_users",
    ],
)
def test_normalized_schema_markers_are_rejected(relation: str) -> None:
    """Normalized-schema relations must never enter the legacy migration path."""
    with pytest.raises(RuntimeError, match="normalized Transsion Core schema"):
        validate_schema_relations({relation})


def test_normalized_schema_is_rejected_even_with_an_alembic_version_table() -> None:
    """A misleading Alembic version table cannot authorize a different schema."""
    with pytest.raises(RuntimeError, match="normalized Transsion Core schema"):
        validate_schema_relations({"alembic_version", "federations"})


def test_unversioned_legacy_relations_are_rejected() -> None:
    """Existing legacy relations without migration history must not be baselined."""
    with pytest.raises(RuntimeError, match="unversioned database"):
        validate_schema_relations({"bans", "tc_owners"})
