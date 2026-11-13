#!/usr/bin/env python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Print the messages of the database guards.

The guards of the community schema are the last line of defence for the
invariants the application relies on. A test that has to match the
message of a guard needs to know what the server says, and the message
lives in the SQL of the schema.

The script builds the schema in the development schema of a server and
prints the message of every guard it can reach.

Usage:

    uv run python scripts/print_guard_messages.py [database-url]

The database URL may be omitted: the script then reads ``DATABASE_URL``
from the environment or from ``config.env``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine, text

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tcbot.database.base import metadata  # noqa: E402
from tcbot.database.migrations import scoped_url  # noqa: E402
from tcbot.database.schema import apply_schema  # noqa: E402

# * The schema the probe owns. The project uses three schemas and no
# * more: ``public`` for the deployment, ``test`` for the integration
# * tests, and ``development`` for a developer working against a shared
# * server.
PROBE_SCHEMA: str = "development"

# * The rows every probe needs before it can reach its guard.
_SETUP: tuple[str, ...] = (
    "INSERT INTO telegram_users (user_id) VALUES (1), (2), (3)",
    "INSERT INTO telegram_chats (chat_id, chat_type, title) "
    "VALUES (-1001, 'supergroup', 'g'), (-500, 'channel', 'c')",
    "INSERT INTO connected_chats (chat_id) VALUES (-1001)",
    "INSERT INTO role_assignments (user_id, role_key) VALUES (1, 'owner')",
    "INSERT INTO moderation_cases (subject_user_id, title) VALUES (3, 'case')",
    "INSERT INTO moderation_actions (action_type, scope_type, target_user_id, "
    "actor_user_id, reason, status, external_ref, case_id, action_origin, chat_id) "
    "VALUES ('warn', 'chat', 3, 1, 'reason', 'completed', 'warn0000001', 1, "
    "'system', -1001)",
    "INSERT INTO moderation_enforcement_runs (action_id, operation, idempotency_key) "
    "VALUES (1, 'apply', 'run-1')",
    "INSERT INTO moderation_enforcement_targets (run_id, chat_id) VALUES (1, -1001)",
    "INSERT INTO audit_events (event_key, entity_type, actor_user_id) "
    "VALUES ('test.event', 'moderation_action', 1)",
)

# * Every guard the probe can reach, with the statement that reaches it.
_PROBES: tuple[tuple[str, str], ...] = (
    (
        "immutable action facts",
        "UPDATE moderation_actions SET external_ref = 'otherhandle1' WHERE id = 1",
    ),
    (
        "immutable reason",
        "UPDATE moderation_actions SET reason = 'other' WHERE id = 1",
    ),
    (
        "group type",
        "INSERT INTO connected_chats (chat_id) VALUES (-500)",
    ),
    (
        "inactive chat decision",
        "INSERT INTO moderation_actions (action_type, scope_type, target_user_id, "
        "actor_user_id, reason, status, external_ref, case_id, action_origin, chat_id) "
        "VALUES ('warn', 'chat', 3, 1, 'reason', 'completed', 'warn0000002', 1, "
        "'system', -999)",
    ),
    (
        "role facts",
        "UPDATE role_assignments SET role_key = 'admin' WHERE id = 1",
    ),
    (
        "second active role",
        "INSERT INTO role_assignments (user_id, role_key) VALUES (1, 'moderator')",
    ),
    (
        "evidence state",
        "INSERT INTO moderation_evidence_uploads (case_id, destination_chat_id, "
        "expected_item_count, is_required, status) "
        "VALUES (1, -1001, 2, true, 'completed')",
    ),
    (
        "ban without proof",
        "INSERT INTO moderation_actions (action_type, scope_type, target_user_id, "
        "actor_user_id, reason, status, external_ref, case_id, action_origin) "
        "VALUES ('ban', 'community', 2, 1, 'reason', 'active', 'ban00000001', 1, "
        "'manual')",
    ),
    (
        "audit entity",
        "INSERT INTO audit_events (event_key, entity_type, entity_id) "
        "VALUES ('test.event', 'moderation_action', '999999999')",
    ),
    (
        "audit rewrite",
        "UPDATE audit_events SET event_key = 'other.event'",
    ),
    (
        "enforcement target state",
        "INSERT INTO moderation_enforcement_targets (run_id, chat_id, status) "
        "VALUES (1, -1001, 'succeeded')",
    ),
    (
        "broadcast audience",
        'SELECT validate_broadcast_audience_filter(\'{"mode": "all_actve"}\'::jsonb)',
    ),
)


def _database_url(argument: str | None) -> str:
    """Return the database URL the probe runs against."""
    if argument:
        return argument
    load_dotenv(find_dotenv("config.env") or find_dotenv(".env"))
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is required; pass it as an argument or set it in "
            "the environment."
        )
    return url


def _sync_url(url: str) -> str:
    """Return *url* with the psycopg 3 driver."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def _scoped_url(url: str, schema: str) -> str:
    """Return *url* with the search path of *schema*."""
    return scoped_url(url, schema)


def main() -> int:
    """Build the schema and print every guard message."""
    url = _database_url(sys.argv[1] if len(sys.argv) > 1 else None)
    scoped = _scoped_url(url, PROBE_SCHEMA)
    engine = create_engine(_sync_url(scoped), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PROBE_SCHEMA}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{PROBE_SCHEMA}"'))
    engine.dispose()

    scoped_engine = create_engine(_sync_url(scoped), pool_pre_ping=True)
    with scoped_engine.begin() as conn:
        metadata.create_all(conn)
        apply_schema(conn)

    with scoped_engine.begin() as conn:
        for statement in _SETUP:
            conn.execute(text(statement))
        for label, statement in _PROBES:
            savepoint = conn.begin_nested()
            try:
                conn.execute(text(statement))
                print(f"{label}: NO ERROR")
            except Exception as exc:
                first = str(exc).splitlines()[0]
                print(f"{label}: {first}")
            savepoint.rollback()
    scoped_engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
