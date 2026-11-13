# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The community migration moves the legacy history into the new tables.

A deployment that runs the revision must keep its bans, mutes, warnings,
kicks, roles, groups, and pending requests. The import is the riskiest
part of the change: it reads the legacy tables, writes the community
tables through the same guards the application uses, and drops the
legacy tables afterwards.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from tests.postgres_support import (
    configured_database_url,
    create_empty_schema,
    drop_schema,
    sync_database_url,
    worker_schema,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Connection

# * Every test in this module needs a real PostgreSQL server.
pytestmark = [pytest.mark.postgres]

# * The migration check owns its own schema: it starts from the legacy
# * schema, so it must not share objects with any other test schema.
_MIGRATION_SCHEMA: str = worker_schema("tcbot_community_migration")

# * The repository root holds alembic.ini and the alembic/ script directory.
_ROOT: Path = Path(__file__).resolve().parents[1]

# * The archive and log chats the legacy proof and log messages live in.
_PROOFS_CHAT: int = -100999
_LOGS_CHAT: int = -100998

# * The rows of the legacy schema. They cover every table the import
# * reads, including a decision in a group that is no longer connected.
_LEGACY_ROWS: tuple[str, ...] = (
    """
    INSERT INTO member_cache (user_id, username, first_name, last_name, last_updated)
    VALUES (1, 'owner', 'Owner', NULL, now()),
           (2, 'mod', 'Mod', NULL, now()),
           (3, 'target', 'Target', NULL, now())
    """,
    """
    INSERT INTO federated_groups (chat_id, title, added_by, added_date, is_active, locale)
    VALUES (-100, 'Group A', 1, now(), true, 'en-US'),
           (-200, 'Group B', 1, now(), false, 'en-US')
    """,
    """
    INSERT INTO tc_owners (user_id) VALUES (1)
    """,
    """
    INSERT INTO tc_admins (user_id, promoted_by, promoted_date) VALUES (2, 1, now())
    """,
    """
    INSERT INTO tc_roles (user_id, role, assigned_by, assigned_at)
    VALUES (4, 'tester', 1, now())
    """,
    """
    INSERT INTO pending_joins (chat_id, title, owner_id, message_id, added_date)
    VALUES (-300, 'Group C', 3, 77, now())
    """,
    """
    INSERT INTO user_settings (user_id, locale) VALUES (3, 'id-ID')
    """,
    """
    INSERT INTO promotion_requests
        (request_id, target_id, username, first_name, promoted_by, status, requested_date)
    VALUES ('req0000001', 4, 'mod', 'Mod', 1, 'pending', now())
    """,
    """
    INSERT INTO bans
        (ban_id, banned_user_id, reason, admin_user_id, proof_message_id,
         log_message_id, timestamp, until_date, duration_str, is_active, update_count)
    VALUES ('abc1234567', 3, 'spam', 1, 501, 502, now(), now() + interval '7 days',
            '7d', true, 0),
           ('def1234567', 5, 'older spam', 2, NULL, NULL, now() - interval '30 days',
            now() - interval '1 day', '1d', false, 1)
    """,
    """
    INSERT INTO mutes (user_id, chat_id, reason, admin_id, timestamp, duration_secs)
    VALUES (5, -100, 'mute reason', 1, now(), 3600)
    """,
    """
    INSERT INTO active_mutes (user_id, until_date, timestamp)
    VALUES (5, now() + interval '1 hour', now())
    """,
    """
    INSERT INTO warns (user_id, chat_id, reason, admin_id, timestamp)
    VALUES (3, -100, 'warn one', 2, now()),
           (3, -100, 'warn two', 2, now()),
           (5, -999, 'warn in a removed group', 2, now())
    """,
    """
    INSERT INTO warn_counts (user_id, chat_id, count, updated_at)
    VALUES (3, -100, 2, now())
    """,
    """
    INSERT INTO kicks (user_id, chat_id, reason, admin_id, timestamp)
    VALUES (5, -100, 'kick reason', 1, now())
    """,
)


def _upgrade(url: str, revision: str, **env: str) -> None:
    """Apply the revisions up to *revision* inside the migration schema.

    The Alembic environment builds its own engine from the URL, so the
    schema scope has to travel through the libpq connection options.
    PGOPTIONS is the libpq environment variable for that.
    """
    previous_options = os.environ.get("PGOPTIONS")
    previous_env = {key: os.environ.get(key) for key in env}
    os.environ["PGOPTIONS"] = f"-c search_path={_MIGRATION_SCHEMA}"
    for key, value in env.items():
        os.environ[key] = value
    try:
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, revision)
    finally:
        if previous_options is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_options
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def migrated_schema() -> Iterator[str]:
    """Yield a schema that was migrated from a seeded legacy schema."""
    url = configured_database_url()
    if url is None:
        pytest.skip("TCBOT_TEST_DATABASE_URL is not set; skipping the migration check.")
    create_empty_schema(url, _MIGRATION_SCHEMA)

    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={_MIGRATION_SCHEMA}"},
    )
    try:
        # * The legacy revision builds the tables the import reads.
        _upgrade(url, "0002")
        with engine.begin() as conn:
            for statement in _LEGACY_ROWS:
                conn.execute(text(statement))
        _upgrade(
            url,
            "head",
            PROOFS=str(_PROOFS_CHAT),
            LOGS=str(_LOGS_CHAT),
        )
        yield _MIGRATION_SCHEMA
    finally:
        engine.dispose()
        drop_schema(url, _MIGRATION_SCHEMA)


def _count(conn: Connection, statement: str) -> int:
    """Return the number of rows one statement selects."""
    return int(conn.execute(text(statement)).scalar() or 0)


def test_the_legacy_identities_move_over(migrated_schema: str) -> None:
    """Every user and group of the legacy schema is registered."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            assert _count(conn, "SELECT count(*) FROM telegram_users") >= 4
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM connected_chats WHERE chat_id IN (-100, -200)",
                )
                == 2
            )
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM telegram_chats WHERE chat_id = -100",
                )
                == 1
            )
    finally:
        engine.dispose()


def test_the_legacy_roles_move_over(migrated_schema: str) -> None:
    """The owner, the admin, and the tester keep their role."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            roles = dict(
                conn.execute(
                    text(
                        "SELECT user_id, role_key FROM role_assignments "
                        "WHERE status = 'active'"
                    )
                ).all()
            )
            assert roles.get(1) == "owner"
            assert roles.get(2) == "admin"
            # * The legacy tester role becomes the moderator of the community.
            assert roles.get(4) == "moderator"
    finally:
        engine.dispose()


def test_the_legacy_decisions_move_over(migrated_schema: str) -> None:
    """Every ban, mute, warning, and kick becomes a decision."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            counts = dict(
                conn.execute(
                    text(
                        "SELECT action_type, count(*) FROM moderation_actions "
                        "GROUP BY action_type"
                    )
                ).all()
            )
            assert counts.get("ban") == 2
            assert counts.get("mute") == 1
            assert counts.get("warn") == 3
            assert counts.get("kick") == 1
            # * Every decision points at the case that holds it.
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM moderation_actions a "
                    "JOIN moderation_cases c ON c.id = a.case_id "
                    "WHERE c.subject_user_id <> a.target_user_id",
                )
                == 0
            )
    finally:
        engine.dispose()


def test_the_active_ban_keeps_its_state_and_its_proof(migrated_schema: str) -> None:
    """The ban that was in force is still in force, with its archived proof."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            active = conn.execute(
                text(
                    "SELECT status, external_ref, action_origin, evidence_upload_id "
                    "FROM moderation_actions WHERE external_ref = 'abc1234567'"
                )
            ).one()
            assert active[0] == "active"
            assert active[1] == "abc1234567"
            assert active[2] == "manual"
            assert active[3] is not None
            # * The archived proof is a completed, required batch.
            upload = conn.execute(
                text(
                    "SELECT status, is_required, expected_item_count "
                    "FROM moderation_evidence_uploads WHERE id = :upload"
                ),
                {"upload": active[3]},
            ).one()
            assert upload[0] == "completed"
            assert upload[1] is True
            assert upload[2] == 1
            # * The log message of the ban moved with it.
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM moderation_messages "
                    "WHERE message_id = 502 AND message_kind = 'log'",
                )
                == 1
            )
    finally:
        engine.dispose()


def test_the_decision_of_a_disconnected_group_stays_readable(
    migrated_schema: str,
) -> None:
    """A warning of a group that is no longer connected is kept."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM moderation_actions "
                    "WHERE action_type = 'warn' AND chat_id = -999",
                )
                == 1
            )
    finally:
        engine.dispose()


def test_the_legacy_tables_are_gone(migrated_schema: str) -> None:
    """The replaced tables do not survive the migration."""
    url = configured_database_url()
    assert url is not None
    engine = create_engine(
        sync_database_url(url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={migrated_schema}"},
    )
    try:
        with engine.connect() as conn:
            remaining = [
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema() "
                        "AND table_type = 'BASE TABLE' AND table_name IN "
                        "('bans', 'mutes', 'warns', 'warn_counts', 'active_mutes', "
                        "'kicks', 'member_cache', 'tc_owners', 'tc_admins', 'tc_roles', "
                        "'federated_groups', 'pending_joins', 'legacy_user_settings', "
                        "'legacy_promotion_requests', 'legacy_warn_counts', "
                        "'legacy_active_mutes')"
                    )
                ).all()
            ]
            assert remaining == [], f"legacy tables left: {remaining}"
    finally:
        engine.dispose()
