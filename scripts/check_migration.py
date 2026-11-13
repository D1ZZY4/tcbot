#!/usr/bin/env python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Verify the community-schema migration against a seeded legacy database.

The migration that moves a legacy deployment onto the community schema
has to carry the history over: the identities, the groups, the staff
assignments, the decisions, and the appeal trail. A migration that loses
a row is not a cosmetic problem, because the history it drops cannot be
reconstructed from Telegram.

The check runs inside a schema of its own, so it never touches the
schema of a deployment. It builds the legacy layout, seeds it with rows
that cover every import path, applies the revisions, and then verifies
that every seeded row arrived in the community tables.

Usage:

    uv run python scripts/check_migration.py <database-url>

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

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from alembic.config import Config  # noqa: E402

from alembic import command  # noqa: E402
from tcbot.database.migrations import scoped_url  # noqa: E402

# * The schema the check owns. The project uses three schemas and no
# * more: ``public`` for the deployment, ``test`` for the integration
# * tests, and ``development`` for a developer working against a shared
# * server. The check runs in the development schema, and it drops that
# * schema when it is done.
CHECK_SCHEMA: str = "development"

# * The revision the legacy layout ends at. The community schema is the
# * revision after it.
LEGACY_REVISION: str = "0002"

# * The legacy rows that cover every import path of the migration: the
# * identities, the connected groups, the staff assignments, the pending
# * connection request, the preferences, the queued promotion, the
# * decisions of every kind, and the counters.
LEGACY_ROWS: tuple[str, ...] = (
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
    INSERT INTO warn_counts (user_id, chat_id, count, updated_at) VALUES (3, -100, 2, now())
    """,
    """
    INSERT INTO kicks (user_id, chat_id, reason, admin_id, timestamp)
    VALUES (5, -100, 'kick reason', 1, now())
    """,
)

# * The legacy rows that the migration has to carry over. The identities
# * and the chats are checked by presence, not by an exact count: the
# * migration also registers the owner and the log destinations of the
# * environment, so the total depends on the deployment.
_SEEDED_USERS: tuple[int, ...] = (1, 2, 3, 4, 5)
_SEEDED_CHATS: tuple[int, ...] = (-100, -200, -300, -999)

# * The tables the community schema replaces. None of them may survive
# * the migration.
_REMOVED_TABLES: tuple[str, ...] = (
    "bans",
    "kicks",
    "mutes",
    "warns",
    "member_cache",
    "tc_owners",
    "tc_admins",
    "tc_roles",
    "federated_groups",
    "pending_joins",
    "legacy_user_settings",
    "legacy_promotion_requests",
    "legacy_warn_counts",
    "legacy_active_mutes",
)


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


def _scoped_url(url: str, schema: str) -> str:
    """Return *url* with the search path of *schema*."""
    return scoped_url(url, schema)


def _alembic_config(url: str) -> Config:
    """Return the Alembic configuration for *url*."""
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _sync_url(url: str) -> str:
    """Return *url* with the psycopg 3 driver."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def _reset_schema(engine: object, schema: str) -> None:
    """Drop and recreate the schema of the check."""
    with engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))


def _seed_legacy(engine: object) -> None:
    """Insert the legacy rows the check needs."""
    with engine.begin() as conn:  # type: ignore[attr-defined]
        for statement in LEGACY_ROWS:
            conn.execute(text(statement))


def _count(conn: Connection, table: str) -> int:
    """Return the row count of *table*."""
    return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)


def _scalar(conn: Connection, statement: str) -> int:
    """Return the single integer a statement produces."""
    return int(conn.execute(text(statement)).scalar() or 0)


def _verify(engine: object) -> list[str]:
    """Return the failures of the migrated database."""
    failures: list[str] = []
    with engine.connect() as conn:  # type: ignore[attr-defined]
        surviving = _scalar(
            conn,
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name IN "
            f"({', '.join(repr(name) for name in _REMOVED_TABLES)})",
        )
        if surviving:
            failures.append(f"{surviving} legacy table(s) survived the migration")

        # * Every identity the legacy rows referred to has to exist, so
        # * the imported history still points at a real user.
        missing_users = _scalar(
            conn,
            "SELECT count(*) FROM ("
            f"  SELECT unnest(ARRAY{list(_SEEDED_USERS)}::bigint[]) AS user_id"
            ") AS seeded WHERE NOT EXISTS ("
            "  SELECT 1 FROM telegram_users WHERE user_id = seeded.user_id"
            ")",
        )
        if missing_users:
            failures.append(f"{missing_users} seeded user(s) did not arrive")

        missing_chats = _scalar(
            conn,
            "SELECT count(*) FROM ("
            f"  SELECT unnest(ARRAY{list(_SEEDED_CHATS)}::bigint[]) AS chat_id"
            ") AS seeded WHERE NOT EXISTS ("
            "  SELECT 1 FROM telegram_chats WHERE chat_id = seeded.chat_id"
            ")",
        )
        if missing_chats:
            failures.append(f"{missing_chats} seeded chat(s) did not arrive")

        # * The connection state of a group has to survive: an active
        # * group stays active and a disconnected one stays disconnected.
        active = _scalar(
            conn,
            "SELECT count(*) FROM connected_chats WHERE chat_id = -100 AND is_active",
        )
        inactive = _scalar(
            conn,
            "SELECT count(*) FROM connected_chats "
            "WHERE chat_id = -200 AND NOT is_active",
        )
        if not active:
            failures.append("the active group did not stay active")
        if not inactive:
            failures.append("the disconnected group did not stay disconnected")

        # * The group configuration has to exist for every connected
        # * group, and the preference of the user has to survive.
        settings = _scalar(
            conn,
            "SELECT count(*) FROM chat_settings cs "
            "JOIN connected_chats cc ON cc.chat_id = cs.chat_id",
        )
        connected = _count(conn, "connected_chats")
        if settings != connected:
            failures.append(
                f"{connected - settings} connected group(s) have no configuration row"
            )
        preference = _scalar(
            conn,
            "SELECT count(*) FROM user_settings WHERE user_id = 3 AND locale = 'id-ID'",
        )
        if not preference:
            failures.append("the locale preference of user 3 did not arrive")

        # * The staff assignments have to arrive with their tier.
        roles = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                text(
                    "SELECT user_id, role_key FROM role_assignments "
                    "WHERE user_id IN (1, 2, 4) AND status = 'active'"
                )
            ).all()
        }
        for user_id, expected in ((1, "owner"), (2, "admin"), (4, "moderator")):
            if roles.get(str(user_id)) != expected:
                failures.append(
                    f"user {user_id} holds {roles.get(str(user_id))!r}, "
                    f"expected {expected!r}"
                )

        queued = _scalar(
            conn,
            "SELECT count(*) FROM promotion_requests WHERE request_id = 'req0000001'",
        )
        if not queued:
            failures.append("the queued promotion request did not arrive")

        pending = _scalar(
            conn, "SELECT count(*) FROM join_requests WHERE chat_id = -300"
        )
        if not pending:
            failures.append("the pending connection request did not arrive")

        # * Every seeded decision has to arrive with its kind, its
        # * target, its group, and its scope.
        decisions: dict[tuple[str, str, str], str] = {}
        for row in conn.execute(
            text(
                "SELECT action_type, target_user_id, "
                "  coalesce(chat_id, 0), scope_type FROM moderation_actions"
            )
        ).all():
            decisions[(str(row[0]), str(row[1]), str(row[2]))] = str(row[3])

        expected_decisions = (
            ("ban", "3", "0", "community"),
            ("ban", "5", "0", "community"),
            ("mute", "5", "0", "community"),
            ("warn", "3", "-100", "chat"),
            ("warn", "3", "-100", "chat"),
            ("warn", "5", "-999", "chat"),
            ("kick", "5", "-100", "chat"),
        )
        for action_type, target, chat_id, scope in expected_decisions:
            found = decisions.get((action_type, target, chat_id))
            if found is None:
                failures.append(
                    f"the {action_type} decision for user {target} "
                    f"in chat {chat_id} did not arrive"
                )
            elif found != scope:
                failures.append(
                    f"the {action_type} decision for user {target} "
                    f"has scope {found}, expected {scope}"
                )

        # * The community decisions carry no group, and the chat
        # * decisions carry theirs.
        unscoped = _scalar(
            conn,
            "SELECT count(*) FROM moderation_actions "
            "WHERE action_type IN ('ban', 'mute') "
            "AND (scope_type <> 'community' OR chat_id IS NOT NULL)",
        )
        if unscoped:
            failures.append(f"{unscoped} community decision(s) carry a chat scope")

        chat_scoped = _scalar(
            conn,
            "SELECT count(*) FROM moderation_actions "
            "WHERE action_type IN ('warn', 'kick') "
            "AND (scope_type <> 'chat' OR chat_id IS NULL)",
        )
        if chat_scoped:
            failures.append(f"{chat_scoped} chat decision(s) miss their group")

        # * The warning of a group that was never connected has to stay
        # * readable: it is the history of a decision.
        dropped_group = _scalar(
            conn,
            "SELECT count(*) FROM moderation_actions "
            "WHERE action_type = 'warn' AND chat_id = -999",
        )
        if dropped_group != 1:
            failures.append(
                f"expected 1 warning of a disconnected group, found {dropped_group}"
            )

        # * The public reference of a decision has to be usable in the
        # * appeal link.
        bad_ref = _scalar(
            conn,
            "SELECT count(*) FROM moderation_actions "
            "WHERE external_ref !~ '^[a-z0-9]{10,32}$'",
        )
        if bad_ref:
            failures.append(f"{bad_ref} decision(s) carry an unusable public reference")

        # * The invariants the community schema promises have to hold
        # * after the import.
        owners = _scalar(
            conn,
            "SELECT count(*) FROM role_assignments "
            "WHERE status = 'active' AND role_key = 'owner'",
        )
        if owners != 1:
            failures.append(f"expected exactly one active owner, found {owners}")

        duplicate = _scalar(
            conn,
            "SELECT count(*) FROM ("
            "  SELECT user_id FROM role_assignments WHERE status = 'active'"
            "  GROUP BY user_id HAVING count(*) > 1"
            ") AS doubled",
        )
        if duplicate:
            failures.append(f"{duplicate} user(s) hold more than one active role")

        duplicated_ban = _scalar(
            conn,
            "SELECT count(*) FROM ("
            "  SELECT target_user_id FROM moderation_actions "
            "  WHERE action_type = 'ban' AND status = 'active'"
            "  GROUP BY target_user_id HAVING count(*) > 1"
            ") AS doubled",
        )
        if duplicated_ban:
            failures.append(f"{duplicated_ban} target(s) hold more than one active ban")

        # * Every decision needs the case that holds its history.
        orphan = _scalar(
            conn,
            "SELECT count(*) FROM moderation_actions a "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM moderation_cases c WHERE c.id = a.case_id"
            ")",
        )
        if orphan:
            failures.append(f"{orphan} decision(s) have no case")
    return failures


def main() -> int:
    """Run the migration check and report the result."""
    url = _database_url(sys.argv[1] if len(sys.argv) > 1 else None)
    scoped = _scoped_url(url, CHECK_SCHEMA)
    # * The schema is created before anything connects to it: a search
    # * path that names a schema nobody created falls back to the next
    # * schema of the path, and the check would then migrate the schema
    # * of the deployment.
    admin = create_engine(_sync_url(url), pool_pre_ping=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CHECK_SCHEMA}"'))
    admin.dispose()

    engine = create_engine(_sync_url(scoped), pool_pre_ping=True)
    try:
        _reset_schema(engine, CHECK_SCHEMA)
        config = _alembic_config(scoped)
        command.upgrade(config, LEGACY_REVISION)
        _seed_legacy(engine)
        command.upgrade(config, "head")
        failures = _verify(engine)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{CHECK_SCHEMA}" CASCADE'))
        engine.dispose()

    if failures:
        print("migration check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("migration check passed: every seeded row arrived in the community schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
