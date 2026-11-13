#!/usr/bin/env python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Check the invariants of the community schema against a real server.

The schema carries the invariants the application relies on: one active
role per user, at most one active owner, a ban without proof is
refused, a chat-scoped decision needs a connected group, an evidence
batch only completes with every item, only the banned user may appeal,
and the audit trail cannot be rewritten.

The check builds the schema in the development schema of a server, runs
the statements that have to fail and the statements that have to
succeed, and reports every invariant that did not hold.

Usage:

    uv run python scripts/check_schema.py [database-url]

The database URL may be omitted: the script then reads ``DATABASE_URL``
from the environment or from ``config.env``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

if TYPE_CHECKING:
    from collections.abc import Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tcbot.database.base import metadata  # noqa: E402
from tcbot.database.migrations import scoped_url  # noqa: E402
from tcbot.database.schema import apply_schema, drop_schema  # noqa: E402

# * The schema the check owns. The project uses three schemas and no
# * more: ``public`` for the deployment, ``test`` for the integration
# * tests, and ``development`` for a developer working against a shared
# * server.
CHECK_SCHEMA: str = "development"


def _database_url(argument: str | None) -> str:
    """Return the database URL the check runs against."""
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


def _expect_failure(conn, failures: list[str], label: str, action: Callable) -> None:
    """Run *action* and record a failure when it did not raise."""
    try:
        with conn.begin_nested():
            action()
    except DatabaseError:
        return
    failures.append(f"{label} was accepted")


def _check(engine: object) -> list[str]:
    """Build the schema and return the invariants that did not hold."""
    failures: list[str] = []
    with engine.begin() as conn:  # type: ignore[attr-defined]
        drop_schema(conn)
        metadata.drop_all(conn, checkfirst=True)
        metadata.create_all(conn, checkfirst=True)
        apply_schema(conn)

        conn.execute(
            text(
                "INSERT INTO telegram_users (user_id, username, first_name) "
                "VALUES (1, 'owner', 'Owner'), (2, 'mod', 'Mod'), (3, 'target', 'T')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO telegram_chats (chat_id, chat_type, title) "
                "VALUES (-100, 'supergroup', 'Group')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO connected_chats (chat_id, added_by_user_id) VALUES (-100, 1)"
            )
        )
        settings = conn.execute(
            text("SELECT count(*) FROM chat_settings WHERE chat_id = -100")
        ).scalar()
        if settings != 1:
            failures.append("chat_settings row was not created")

        conn.execute(
            text(
                "INSERT INTO role_assignments (user_id, role_key, assigned_by_user_id) "
                "VALUES (1, 'owner', 1)"
            )
        )
        has_perm = conn.execute(
            text("SELECT actor_has_permission(1, 'roles.transfer_ownership')")
        ).scalar()
        if has_perm is not True:
            failures.append("the owner is missing a permission")

        _expect_failure(
            conn,
            failures,
            "a second active role",
            lambda: conn.execute(
                text(
                    "INSERT INTO role_assignments "
                    "(user_id, role_key, assigned_by_user_id) VALUES (1, 'admin', 1)"
                )
            ),
        )
        _expect_failure(
            conn,
            failures,
            "a second active owner",
            lambda: conn.execute(
                text(
                    "INSERT INTO role_assignments "
                    "(user_id, role_key, assigned_by_user_id) VALUES (2, 'owner', 1)"
                )
            ),
        )

        conn.execute(
            text(
                "INSERT INTO moderation_cases "
                "(subject_user_id, title, opened_by_user_id) VALUES (3, 'spam', 1)"
            )
        )
        case_id = conn.execute(
            text("SELECT id FROM moderation_cases WHERE subject_user_id = 3")
        ).scalar()

        _expect_failure(
            conn,
            failures,
            "a ban without proof",
            lambda: conn.execute(
                text(
                    "INSERT INTO moderation_actions "
                    "(action_type, target_user_id, actor_user_id, reason, "
                    " case_id, status, scope_type, action_origin) "
                    "VALUES ('ban', 3, 1, 'spam', :case, 'active', 'community', "
                    "'manual')"
                ),
                {"case": case_id},
            ),
        )
        _expect_failure(
            conn,
            failures,
            "a chat scoped ban",
            lambda: conn.execute(
                text(
                    "INSERT INTO moderation_actions "
                    "(action_type, target_user_id, actor_user_id, reason, "
                    " case_id, status, scope_type, chat_id, action_origin) "
                    "VALUES ('ban', 3, 1, 'spam', :case, 'active', 'chat', -100, "
                    "'manual')"
                ),
                {"case": case_id},
            ),
        )
        _expect_failure(
            conn,
            failures,
            "a warn in an unknown group",
            lambda: conn.execute(
                text(
                    "INSERT INTO moderation_actions "
                    "(action_type, target_user_id, actor_user_id, reason, "
                    " case_id, status, scope_type, chat_id, action_origin) "
                    "VALUES ('warn', 3, 1, 'spam', :case, 'completed', 'chat', -999, "
                    "'manual')"
                ),
                {"case": case_id},
            ),
        )

        conn.execute(
            text(
                "INSERT INTO moderation_evidence_uploads "
                "(case_id, destination_chat_id, expected_item_count, is_required, "
                " status, uploaded_by_user_id) "
                "VALUES (:case, -100, 2, true, 'queued', 1)"
            ),
            {"case": case_id},
        )
        upload_id = conn.execute(
            text("SELECT id FROM moderation_evidence_uploads")
        ).scalar()
        # * A batch starts queued and moves to uploading when the worker
        # * claims it.
        conn.execute(
            text(
                "UPDATE moderation_evidence_uploads SET status = 'uploading', "
                "started_at = now() WHERE id = :upload"
            ),
            {"upload": upload_id},
        )
        conn.execute(
            text(
                "INSERT INTO moderation_evidence_items "
                "(upload_id, destination_chat_id, archive_message_id, media_type, "
                " item_order) VALUES (:upload, -100, 55, 'photo', 0)"
            ),
            {"upload": upload_id},
        )
        _expect_failure(
            conn,
            failures,
            "a completed batch with a missing item",
            lambda: conn.execute(
                text(
                    "UPDATE moderation_evidence_uploads SET status = 'completed' "
                    "WHERE id = :upload"
                ),
                {"upload": upload_id},
            ),
        )
        conn.execute(
            text(
                "INSERT INTO moderation_evidence_items "
                "(upload_id, destination_chat_id, archive_message_id, media_type, "
                " item_order) VALUES (:upload, -100, 56, 'photo', 1)"
            ),
            {"upload": upload_id},
        )
        conn.execute(
            text(
                "UPDATE moderation_evidence_uploads SET status = 'completed', "
                "primary_message_id = 55 WHERE id = :upload"
            ),
            {"upload": upload_id},
        )
        completed = conn.execute(
            text("SELECT status FROM moderation_evidence_uploads WHERE id = :upload"),
            {"upload": upload_id},
        ).scalar()
        if completed != "completed":
            failures.append("the completed evidence batch was not accepted")

        conn.execute(
            text(
                "INSERT INTO moderation_actions "
                "(action_type, target_user_id, actor_user_id, reason, case_id, "
                " status, scope_type, action_origin, evidence_upload_id) "
                "VALUES ('ban', 3, 1, 'spam', :case, 'active', 'community', 'manual', "
                ":upload)"
            ),
            {"case": case_id, "upload": upload_id},
        )
        action_id = conn.execute(text("SELECT id FROM moderation_actions")).scalar()
        ref = conn.execute(text("SELECT external_ref FROM moderation_actions")).scalar()
        if not ref or not (10 <= len(ref) <= 32):
            failures.append(f"the external reference is malformed: {ref!r}")

        conn.execute(
            text(
                "INSERT INTO moderation_appeals "
                "(action_id, appellant_user_id, appeal_text) "
                "VALUES (:action, 3, 'please reconsider')"
            ),
            {"action": action_id},
        )
        _expect_failure(
            conn,
            failures,
            "an appeal by another user",
            lambda: conn.execute(
                text(
                    "INSERT INTO moderation_appeals "
                    "(action_id, appellant_user_id, appeal_text) "
                    "VALUES (:action, 2, 'wrong subject')"
                ),
                {"action": action_id},
            ),
        )

        conn.execute(
            text(
                "INSERT INTO audit_events (event_key, entity_type, actor_user_id) "
                "VALUES ('moderation.ban.created', 'moderation_action', 1)"
            )
        )
        _expect_failure(
            conn,
            failures,
            "an update of the audit trail",
            lambda: conn.execute(text("UPDATE audit_events SET event_key = 'changed'")),
        )

        counts = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM active_bans), "
                "(SELECT count(*) FROM active_mutes), "
                "(SELECT count(*) FROM warn_counts), "
                "(SELECT count(*) FROM community_members), "
                "(SELECT count(*) FROM community_member_stats), "
                "(SELECT count(*) FROM role_permission_matrix), "
                "(SELECT count(*) FROM moderation_timeline), "
                "(SELECT count(*) FROM effective_chat_settings)"
            )
        ).one()
        if tuple(counts) != (1, 0, 0, 0, 1, 4, 6, 1):
            failures.append(f"the views returned unexpected counts: {tuple(counts)}")
    return failures


def main() -> int:
    """Run the invariant checks and report the result."""
    url = _database_url(sys.argv[1] if len(sys.argv) > 1 else None)
    scoped = _scoped_url(url, CHECK_SCHEMA)
    # * The schema is created before anything connects to it: a search
    # * path that names a schema nobody created falls back to the next
    # * schema of the path, and the check would then rebuild the schema
    # * of the deployment.
    admin = create_engine(_sync_url(url), pool_pre_ping=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CHECK_SCHEMA}"'))
    admin.dispose()

    engine = create_engine(_sync_url(scoped), pool_pre_ping=True)
    try:
        failures = _check(engine)
    finally:
        engine.dispose()

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
