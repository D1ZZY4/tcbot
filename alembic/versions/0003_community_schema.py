# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Move the database onto the community schema.

The revision creates the tables of the community model, imports the
history of the tables it replaces, and removes the tables that are
gone. The views, the functions, the triggers, the access policies, and
the reference data are applied from ``tcbot.database.schema``.

Revision ID: 0003_community_schema
Revises: 0002_member_cache_sort_indexes
Create Date: 2026-11-13
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import msgspec
from sqlalchemy import text

from alembic import op
from tcbot.database.base import metadata
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


revision: str = "0003_community_schema"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# * The public handle of a decision is a short lowercase token. A legacy
# * identifier that does not match it is replaced by a digest of itself,
# * so the handle of an imported decision is usable in a link.
_PUBLIC_REF_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]{10,32}$")

# * The legacy tables that share their name with a table of the new
# * schema. They are renamed first, so the new table can be created and
# * the history can be imported into it.
_RENAMED_LEGACY_TABLES: tuple[tuple[str, str], ...] = (
    ("user_settings", "legacy_user_settings"),
    ("promotion_requests", "legacy_promotion_requests"),
    ("warn_counts", "legacy_warn_counts"),
    ("active_mutes", "legacy_active_mutes"),
)

# * The legacy tables that the new schema replaces.
_DROPPED_LEGACY_TABLES: tuple[str, ...] = (
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


def _chat_id(raw: str) -> int | None:
    """Return the chat id of a ``chat_id`` or ``chat_id/thread_id`` value."""
    value = raw.strip().split("/", 1)[0].strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _env_chat_id(name: str) -> int | None:
    """Return the chat id of an environment variable, when it holds one."""
    return _chat_id(os.getenv(name, ""))


def _env_warn_expiry_days() -> int | None:
    """Return the configured warning lifetime in days, when it is set."""
    raw = os.getenv("WARN_EXPIRY_DAYS", "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        return None
    return days if days > 0 else None


def _import_legacy_data(bind) -> None:
    """Move the history of the legacy tables into the new schema."""
    proofs_chat = _env_chat_id("PROOFS")
    logs_chat = _env_chat_id("LOGS")
    warn_expiry_days = _env_warn_expiry_days()

    # * The users the legacy tables refer to. The profile of a user that
    # * is not in the member cache is unknown, but the history still
    # * needs the identity to point at.
    bind.execute(
        text(
            """
            INSERT INTO telegram_users (user_id, created_at, updated_at)
            SELECT DISTINCT source.user_id, now(), now()
            FROM (
                SELECT user_id FROM member_cache
                UNION SELECT user_id FROM tc_owners
                UNION SELECT user_id FROM tc_admins
                UNION SELECT user_id FROM tc_roles
                UNION SELECT banned_user_id FROM bans
                UNION SELECT admin_user_id FROM bans
                UNION SELECT user_id FROM mutes
                UNION SELECT admin_id FROM mutes
                UNION SELECT user_id FROM warns
                UNION SELECT admin_id FROM warns
                UNION SELECT user_id FROM kicks
                UNION SELECT admin_id FROM kicks
                UNION SELECT owner_id FROM pending_joins
                UNION SELECT added_by FROM federated_groups
                UNION SELECT user_id FROM legacy_user_settings
                UNION SELECT target_id FROM legacy_promotion_requests
                UNION SELECT promoted_by FROM legacy_promotion_requests
            ) AS source
            WHERE source.user_id IS NOT NULL
              AND source.user_id > 0
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    )
    # * The legacy rows carry the actor id zero when the moderator is
    # * unknown. The zero is a sentinel, not a Telegram user.
    bind.execute(
        text(
            """
            INSERT INTO telegram_users (user_id, created_at, updated_at)
            VALUES (0, now(), now())
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE telegram_users u
            SET username = m.username,
                first_name = m.first_name,
                last_name = m.last_name,
                created_at = COALESCE(m.commit_date, u.created_at),
                updated_at = m.last_updated
            FROM member_cache m
            WHERE u.user_id = m.user_id
            """
        )
    )

    # * The chats the legacy tables refer to.
    bind.execute(
        text(
            """
            INSERT INTO telegram_chats (chat_id, chat_type, title, created_at, updated_at)
            SELECT f.chat_id, 'supergroup', f.title, f.added_date, f.added_date
            FROM federated_groups f
            ON CONFLICT (chat_id) DO NOTHING
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO telegram_chats (chat_id, chat_type, title, created_at, updated_at)
            SELECT p.chat_id, 'supergroup', p.title, p.added_date, p.added_date
            FROM pending_joins p
            ON CONFLICT (chat_id) DO NOTHING
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO telegram_chats (chat_id, chat_type, created_at, updated_at)
            SELECT DISTINCT source.chat_id, 'supergroup', now(), now()
            FROM (
                SELECT chat_id FROM warns
                UNION SELECT chat_id FROM kicks
                UNION SELECT chat_id FROM mutes
                UNION SELECT chat_id FROM pending_joins
            ) AS source
            WHERE NOT EXISTS (
                SELECT 1 FROM telegram_chats t WHERE t.chat_id = source.chat_id
            )
            ON CONFLICT (chat_id) DO NOTHING
            """
        )
    )
    if logs_chat is not None:
        bind.execute(
            text(
                """
                INSERT INTO telegram_chats (chat_id, chat_type, created_at, updated_at)
                VALUES (:chat_id, 'channel', now(), now())
                ON CONFLICT (chat_id) DO NOTHING
                """
            ),
            {"chat_id": logs_chat},
        )
    if proofs_chat is not None:
        bind.execute(
            text(
                """
                INSERT INTO telegram_chats (chat_id, chat_type, created_at, updated_at)
                VALUES (:chat_id, 'channel', now(), now())
                ON CONFLICT (chat_id) DO NOTHING
                """
            ),
            {"chat_id": proofs_chat},
        )

    # * The managed groups. A group that is no longer in the registry
    # * stays as an inactive row, so the history still points at it.
    bind.execute(
        text(
            """
            INSERT INTO connected_chats (
                chat_id, added_by_user_id, added_at, is_active
            )
            SELECT f.chat_id, f.added_by, f.added_date, f.is_active
            FROM federated_groups f
            ON CONFLICT (chat_id) DO NOTHING
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO connected_chats (
                chat_id, added_by_user_id, added_at, is_active
            )
            SELECT DISTINCT source.chat_id, CAST(NULL AS bigint), now(), true
            FROM (
                SELECT chat_id FROM warns
                UNION SELECT chat_id FROM kicks
            ) AS source
            WHERE NOT EXISTS (
                SELECT 1 FROM connected_chats c WHERE c.chat_id = source.chat_id
            )
            ON CONFLICT (chat_id) DO NOTHING
            """
        )
    )

    # * The group configuration. The trigger that prepares the settings
    # * of a new group already wrote the row when the group was
    # * connected, so the locale is filled in with an update: a plain
    # * insert would be skipped and every group would lose the locale
    # * it had.
    bind.execute(
        text(
            """
            INSERT INTO chat_settings (chat_id, locale, created_at, updated_at)
            SELECT f.chat_id, f.locale, f.added_date, f.added_date
            FROM federated_groups f
            ON CONFLICT (chat_id) DO UPDATE SET
                locale = COALESCE(EXCLUDED.locale, chat_settings.locale),
                updated_at = EXCLUDED.updated_at
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO user_settings (user_id, locale, created_at, updated_at)
            SELECT s.user_id, s.locale, now(), now()
            FROM legacy_user_settings s
            ON CONFLICT (user_id) DO UPDATE SET
                locale = COALESCE(EXCLUDED.locale, user_settings.locale),
                updated_at = EXCLUDED.updated_at
            """
        )
    )

    # * The join requests that never came to a decision.
    bind.execute(
        text(
            """
            INSERT INTO join_requests (
                chat_id, owner_user_id, request_message_id, status, requested_at
            )
            SELECT p.chat_id, p.owner_id, p.message_id, 'pending', p.added_date
            FROM pending_joins p
            ON CONFLICT DO NOTHING
            """
        )
    )

    # * The staff roles. The legacy tester role becomes the moderator.
    bind.execute(
        text(
            """
            INSERT INTO role_assignments (
                user_id, role_key, assigned_by_user_id, assigned_at, status
            )
            SELECT o.user_id, 'owner', NULL, now(), 'active'
            FROM tc_owners o
            WHERE NOT EXISTS (
                SELECT 1 FROM role_assignments r
                WHERE r.user_id = o.user_id AND r.status = 'active'
            )
            ORDER BY o.user_id
            LIMIT 1
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO role_assignments (
                user_id, role_key, assigned_by_user_id, assigned_at, status
            )
            SELECT a.user_id, 'admin', a.promoted_by, a.promoted_date, 'active'
            FROM tc_admins a
            WHERE NOT EXISTS (
                SELECT 1 FROM role_assignments r
                WHERE r.user_id = a.user_id AND r.status = 'active'
            )
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO role_assignments (
                user_id, role_key, assigned_by_user_id, assigned_at, status
            )
            SELECT r.user_id,
                   CASE r.role WHEN 'tester' THEN 'moderator' ELSE 'developer' END,
                   r.assigned_by,
                   r.assigned_at,
                   'active'
            FROM tc_roles r
            WHERE NOT EXISTS (
                SELECT 1 FROM role_assignments existing
                WHERE existing.user_id = r.user_id AND existing.status = 'active'
            )
            """
        )
    )

    # * The promotion requests.
    bind.execute(
        text(
            """
            INSERT INTO promotion_requests (
                request_id,
                target_user_id,
                requested_role_key,
                requested_by_user_id,
                status,
                requested_at,
                resolved_at,
                resolved_by_user_id,
                metadata
            )
            SELECT p.request_id,
                   p.target_id,
                   'admin',
                   p.promoted_by,
                   p.status,
                   p.requested_date,
                   p.resolved_date,
                   p.resolved_by,
                   jsonb_build_object(
                       'username', p.username,
                       'first_name', p.first_name,
                       'legacy_table', 'promotion_requests'
                   )
            FROM legacy_promotion_requests p
            ON CONFLICT (request_id) DO NOTHING
            """
        )
    )

    _import_moderation_history(bind, proofs_chat, logs_chat, warn_expiry_days)

    # * The groups that only appear in the history are managed while the
    # * decisions are imported, because a decision of a group has to
    # * name a group the community manages. They leave the registry
    # * again right after: the community does not manage them.
    bind.execute(
        text(
            """
            UPDATE connected_chats c
            SET is_active = false
            WHERE c.added_by_user_id IS NULL
              AND c.is_active
              AND NOT EXISTS (
                  SELECT 1 FROM federated_groups f WHERE f.chat_id = c.chat_id
              )
            """
        )
    )

    bind.execute(text("SET LOCAL tcbot.migration = 'off'"))


def _import_bans(bind) -> None:
    """Move the ban history into the new schema.

    A ban that is no longer in force is imported before the one that
    still is: a target holds one active ban, so every imported ban has
    to leave the active state before the next one for the same target
    is written.
    """
    rows = (
        bind.execute(
            text(
                "SELECT ban_id, banned_user_id, admin_user_id, reason, "
                "proof_message_id, log_message_id, timestamp, until_date, "
                "duration_str, is_active, update_count FROM bans"
            )
        )
        .mappings()
        .all()
    )
    now = bind.execute(text("SELECT now()")).scalar()
    ordered = sorted(rows, key=lambda row: (bool(row["is_active"]), str(row["ban_id"])))
    for row in ordered:
        _import_ban(bind, row, now)


def _import_ban(bind, row: Mapping[str, Any], now: datetime) -> None:
    """Move one legacy ban into the new schema."""
    legacy_id = str(row["ban_id"])
    case_id = bind.execute(
        text(
            "SELECT id FROM moderation_cases "
            "WHERE metadata ->> 'legacy_table' = 'bans' "
            "AND metadata ->> 'legacy_id' = :legacy_id"
        ),
        {"legacy_id": legacy_id},
    ).scalar()
    if case_id is None:
        return

    until_date = row["until_date"]
    created_at = row["timestamp"]
    in_force = bool(row["is_active"]) and (until_date is None or until_date > now)
    # * A new decision may not carry an expiry that already passed, so
    # * an elapsed expiry is moved one second past the moment the
    # * decision was taken. The exact legacy moment stays in the
    # * metadata of the decision.
    expires_at = until_date
    if expires_at is not None and expires_at <= created_at:
        expires_at = created_at + timedelta(seconds=1)

    upload_id = bind.execute(
        text(
            "SELECT id FROM moderation_evidence_uploads "
            "WHERE case_id = :case_id AND status = 'completed' AND is_required"
        ),
        {"case_id": int(case_id)},
    ).scalar()

    action_id = bind.execute(
        text(
            """
            INSERT INTO moderation_actions (
                action_type,
                scope_type,
                target_user_id,
                actor_user_id,
                reason,
                created_at,
                expires_at,
                status,
                external_ref,
                metadata,
                case_id,
                action_origin,
                evidence_upload_id
            )
            VALUES (
                'ban', 'community', :target, :actor, :reason, :created_at,
                :expires_at, 'active', :external_ref, CAST(:metadata AS jsonb),
                :case_id, :origin, :upload_id
            )
            RETURNING id
            """
        ),
        {
            "target": row["banned_user_id"],
            "actor": row["admin_user_id"],
            "reason": row["reason"],
            "created_at": created_at,
            "expires_at": expires_at,
            "external_ref": (
                legacy_id
                if _PUBLIC_REF_PATTERN.fullmatch(legacy_id)
                else hashlib.md5(legacy_id.encode()).hexdigest()[:16]
            ),
            "metadata": msgspec.json.encode(
                {
                    "legacy_table": "bans",
                    "legacy_ban_id": legacy_id,
                    "legacy_until_date": (
                        until_date.isoformat() if until_date is not None else None
                    ),
                    "duration_str": row["duration_str"],
                    "update_count": row["update_count"],
                    "proof_message_id": row["proof_message_id"],
                    "log_message_id": row["log_message_id"],
                }
            ).decode(),
            "case_id": int(case_id),
            "origin": "manual" if upload_id is not None else "automated",
            "upload_id": upload_id,
        },
    ).scalar()
    if action_id is None or in_force:
        return

    # * The decision is history, so it leaves the active state. A ban
    # * whose expiry has passed is expired, every other one is revoked.
    expired = until_date is not None and until_date <= now
    bind.execute(
        text(
            """
            UPDATE moderation_actions
            SET status = :status,
                revoked_at = :revoked_at,
                revoked_by_user_id = :revoked_by
            WHERE id = :id
            """
        ),
        {
            "status": "expired" if expired else "revoked",
            "revoked_at": None if expired else created_at,
            "revoked_by": None if expired else row["admin_user_id"],
            "id": int(action_id),
        },
    )


def _import_mutes(bind) -> None:
    """Move the mute history into the new schema.

    A mute is a community decision now, so the mute of one group
    becomes a mute of the whole community.
    """
    rows = (
        bind.execute(
            text(
                "SELECT m.id, m.user_id, m.admin_id, m.reason, m.chat_id, "
                "m.timestamp, m.duration_secs, am.until_date, c.id AS case_id "
                "FROM mutes m "
                "LEFT JOIN legacy_active_mutes am ON am.user_id = m.user_id "
                "LEFT JOIN moderation_cases c "
                "  ON c.metadata ->> 'legacy_table' = 'mutes' "
                " AND c.metadata ->> 'legacy_id' = "
                "     m.id || '-' || m.user_id || '-' || m.timestamp"
            )
        )
        .mappings()
        .all()
    )
    now = bind.execute(text("SELECT now()")).scalar()
    ordered = sorted(
        rows,
        key=lambda row: (
            row["until_date"] is not None and row["until_date"] > now,
            str(row["id"]),
        ),
    )
    for row in ordered:
        _import_mute(bind, row, now)


def _import_mute(bind, row: Mapping[str, Any], now: datetime) -> None:
    """Move one legacy mute into the new schema."""
    case_id = row["case_id"]
    if case_id is None:
        return
    legacy_id = f"{row['id']}-{row['user_id']}-{row['timestamp']}"
    until_date = row["until_date"]
    created_at = row["timestamp"]
    in_force = until_date is not None and until_date > now
    expires_at = until_date
    if expires_at is not None and expires_at <= created_at:
        expires_at = created_at + timedelta(seconds=1)

    action_id = bind.execute(
        text(
            """
            INSERT INTO moderation_actions (
                action_type,
                scope_type,
                target_user_id,
                actor_user_id,
                reason,
                duration_seconds,
                created_at,
                expires_at,
                status,
                external_ref,
                metadata,
                case_id,
                action_origin,
                origin_chat_id
            )
            VALUES (
                'mute', 'community', :target, :actor, :reason, :duration,
                :created_at, :expires_at, 'active', :external_ref,
                CAST(:metadata AS jsonb), :case_id, 'system', :origin_chat_id
            )
            RETURNING id
            """
        ),
        {
            "target": row["user_id"],
            "actor": row["admin_id"] or 0,
            "reason": row["reason"],
            "duration": row["duration_secs"],
            "created_at": created_at,
            "expires_at": expires_at,
            "external_ref": hashlib.md5(
                f"mute:{row['id']}:{row['user_id']}".encode()
            ).hexdigest()[:16],
            "metadata": msgspec.json.encode(
                {
                    "legacy_table": "mutes",
                    "legacy_id": legacy_id,
                    "legacy_until_date": (
                        until_date.isoformat() if until_date is not None else None
                    ),
                }
            ).decode(),
            "case_id": int(case_id),
            "origin_chat_id": row["chat_id"],
        },
    ).scalar()
    if action_id is None or in_force:
        return

    bind.execute(
        text(
            """
            UPDATE moderation_actions
            SET status = :status,
                revoked_at = :revoked_at,
                revoked_by_user_id = :revoked_by
            WHERE id = :id
            """
        ),
        {
            "status": "expired"
            if until_date is not None and until_date <= now
            else "revoked",
            "revoked_at": created_at,
            "revoked_by": row["admin_id"] or 0,
            "id": int(action_id),
        },
    )


def _import_moderation_history(
    bind,
    proofs_chat: int | None,
    logs_chat: int | None,
    warn_expiry_days: int | None,
) -> None:
    """Move the ban, mute, warn, and kick history into the new schema."""
    # * Every legacy decision becomes a case and an action. The case
    # * carries the investigation, the action carries the decision.
    # * The table and column names come from the fixed list below, so
    # * the interpolation cannot carry user input.
    case_sources: tuple[tuple[str, str, str, str, str, str], ...] = (
        (
            "bans",
            "Imported ban",
            "banned_user_id",
            "admin_user_id",
            "src.timestamp",
            "src.ban_id",
        ),
        (
            "mutes",
            "Imported mute",
            "user_id",
            "admin_id",
            "src.timestamp",
            "src.id || '-' || src.user_id || '-' || src.timestamp",
        ),
        (
            "warns",
            "Imported warning",
            "user_id",
            "admin_id",
            "src.timestamp",
            "src.id || '-' || src.user_id || '-' || src.chat_id || '-' || src.timestamp",
        ),
        (
            "kicks",
            "Imported kick",
            "user_id",
            "admin_id",
            "src.timestamp",
            "src.id || '-' || src.user_id || '-' || src.chat_id || '-' || src.timestamp",
        ),
    )
    for source, title, subject, actor, created, legacy_id in case_sources:
        bind.execute(
            text(
                f"""
                INSERT INTO moderation_cases (
                    subject_user_id,
                    case_type,
                    title,
                    summary,
                    severity,
                    status,
                    source,
                    opened_by_user_id,
                    created_at,
                    updated_at,
                    requires_evidence,
                    metadata
                )
                SELECT
                    row_data.subject,
                    'rule_violation',
                    :title || ' ' || row_data.legacy_id,
                    row_data.reason,
                    'unknown',
                    'open',
                    'system',
                    row_data.actor,
                    row_data.created_at,
                    row_data.created_at,
                    false,
                    jsonb_build_object(
                        'legacy_table', CAST(:source AS text),
                        'legacy_id', row_data.legacy_id
                    )
                FROM (
                    SELECT
                        src.{subject} AS subject,
                        COALESCE(src.{actor}, 0) AS actor,
                        {created} AS created_at,
                        src.reason,
                        {legacy_id} AS legacy_id
                    FROM {source} AS src
                ) AS row_data
                WHERE NOT EXISTS (
                    SELECT 1 FROM moderation_cases c
                    WHERE c.metadata ->> 'legacy_table' = CAST(:source AS text)
                      AND c.metadata ->> 'legacy_id' = row_data.legacy_id
                )
                """
            ),
            {"title": title, "source": source},
        )

    # * The archived proof of the bans. The proof is a message in the
    # * archive chat, and the archive chat is known from the
    # * configuration.
    #
    # * The batch walks the lifecycle of the table: it is queued when it
    # * is written, the worker claims it, the archived item lands, and
    # * the batch closes as completed once its items are in place.
    if proofs_chat is not None:
        bind.execute(
            text(
                """
                INSERT INTO moderation_evidence_uploads (
                    case_id,
                    destination_chat_id,
                    expected_item_count,
                    is_required,
                    status,
                    uploaded_by_user_id,
                    created_at,
                    updated_at,
                    metadata
                )
                SELECT c.id, :proofs_chat, 1, true, 'queued', b.admin_user_id,
                       b.timestamp, b.timestamp,
                       jsonb_build_object('legacy_table', 'bans')
                FROM bans b
                JOIN moderation_cases c
                  ON c.metadata ->> 'legacy_table' = 'bans'
                 AND c.metadata ->> 'legacy_id' = b.ban_id
                WHERE b.proof_message_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM moderation_evidence_uploads u
                      WHERE u.case_id = c.id
                  )
                """
            ),
            {"proofs_chat": proofs_chat},
        )
        bind.execute(
            text(
                """
                UPDATE moderation_evidence_uploads u
                SET status = 'uploading'
                WHERE u.status = 'queued'
                  AND u.metadata ->> 'legacy_table' = 'bans'
                """
            )
        )
        bind.execute(
            text(
                """
                INSERT INTO moderation_evidence_items (
                    upload_id,
                    destination_chat_id,
                    archive_message_id,
                    media_type,
                    item_order,
                    created_at
                )
                SELECT u.id, u.destination_chat_id, b.proof_message_id, 'photo', 0,
                       b.timestamp
                FROM bans b
                JOIN moderation_evidence_uploads u
                  ON u.case_id = (
                      SELECT c.id FROM moderation_cases c
                      WHERE c.metadata ->> 'legacy_table' = 'bans'
                        AND c.metadata ->> 'legacy_id' = b.ban_id
                  )
                WHERE b.proof_message_id IS NOT NULL
                ON CONFLICT DO NOTHING
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE moderation_evidence_uploads u
                SET status = 'completed',
                    primary_message_id = i.archive_message_id,
                    updated_at = u.created_at
                FROM moderation_evidence_items i
                WHERE i.upload_id = u.id
                  AND i.item_order = 0
                  AND u.status = 'uploading'
                  AND (SELECT count(*) FROM moderation_evidence_items c
                       WHERE c.upload_id = u.id) = u.expected_item_count
                """
            )
        )

    # * The bans. A target holds one active ban, so the bans that are
    # * no longer in force are imported first and leave the active
    # * state right away.
    _import_bans(bind)

    # * The mutes. The legacy live table says which mute is still in
    # * force.
    _import_mutes(bind)

    # * The warnings. They are bound to the group they happened in.
    bind.execute(
        text(
            """
            INSERT INTO moderation_actions (
                action_type,
                target_user_id,
                actor_user_id,
                reason,
                created_at,
                expires_at,
                status,
                external_ref,
                metadata,
                case_id,
                scope_type,
                action_origin,
                chat_id,
                origin_chat_id
            )
            SELECT
                'warn',
                w.user_id,
                COALESCE(w.admin_id, 0),
                w.reason,
                w.timestamp,
                CASE
                    WHEN CAST(:warn_expiry_days AS integer) IS NULL THEN NULL
                    -- * A warning that had already run out keeps an
                    -- * expiry one second past the moment it was filed:
                    -- * the schema rejects an expiry that lies before the
                    -- * decision it belongs to, and the exact legacy
                    -- * deadline stays in the metadata of the decision.
                    ELSE GREATEST(
                        w.timestamp + make_interval(
                            days => CAST(:warn_expiry_days AS integer)
                        ),
                        w.timestamp + interval '1 second'
                    )
                END,
                'completed',
                substr(md5('warn:' || w.id || ':' || w.user_id), 1, 16),
                jsonb_build_object(
                    'legacy_table', 'warns',
                    'legacy_id', w.id || '-' || w.user_id || '-' || w.chat_id || '-' || w.timestamp
                ),
                c.id,
                'chat',
                'system',
                w.chat_id,
                w.chat_id
            FROM warns w
            JOIN moderation_cases c
              ON c.metadata ->> 'legacy_table' = 'warns'
             AND c.metadata ->> 'legacy_id' = w.id || '-' || w.user_id || '-' || w.chat_id || '-' || w.timestamp
            WHERE NOT EXISTS (
                SELECT 1 FROM moderation_actions a
                WHERE a.metadata ->> 'legacy_table' = 'warns'
                  AND a.metadata ->> 'legacy_id' = w.id || '-' || w.user_id || '-' || w.chat_id || '-' || w.timestamp
            )
            """,
        ),
        {"warn_expiry_days": warn_expiry_days},
    )

    # * The kicks.
    bind.execute(
        text(
            """
            INSERT INTO moderation_actions (
                action_type,
                target_user_id,
                actor_user_id,
                reason,
                created_at,
                status,
                external_ref,
                metadata,
                case_id,
                scope_type,
                action_origin,
                chat_id,
                origin_chat_id
            )
            SELECT
                'kick',
                k.user_id,
                COALESCE(k.admin_id, 0),
                k.reason,
                k.timestamp,
                'completed',
                substr(md5('kick:' || k.id || ':' || k.user_id), 1, 16),
                jsonb_build_object(
                    'legacy_table', 'kicks',
                    'legacy_id', k.id || '-' || k.user_id || '-' || k.chat_id || '-' || k.timestamp
                ),
                c.id,
                'chat',
                'system',
                k.chat_id,
                k.chat_id
            FROM kicks k
            JOIN moderation_cases c
              ON c.metadata ->> 'legacy_table' = 'kicks'
             AND c.metadata ->> 'legacy_id' = k.id || '-' || k.user_id || '-' || k.chat_id || '-' || k.timestamp
            WHERE NOT EXISTS (
                SELECT 1 FROM moderation_actions a
                WHERE a.metadata ->> 'legacy_table' = 'kicks'
                  AND a.metadata ->> 'legacy_id' = k.id || '-' || k.user_id || '-' || k.chat_id || '-' || k.timestamp
            )
            """
        )
    )

    # * The Telegram messages that belong to the imported decisions.
    if logs_chat is not None:
        for column, kind in (
            ("log_message_id", "log"),
            ("review_message_id", "review"),
            ("appeal_log_msg_id", "appeal_log"),
        ):
            bind.execute(
                text(
                    f"""
                    INSERT INTO moderation_messages (
                        action_id,
                        chat_id,
                        message_id,
                        message_kind,
                        recorded_by_user_id,
                        created_at
                    )
                    SELECT a.id, :logs_chat, b.{column}, :kind, b.admin_user_id,
                           b.timestamp
                    FROM bans b
                    JOIN moderation_actions a
                      ON a.metadata ->> 'legacy_ban_id' = b.ban_id
                    WHERE b.{column} IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM moderation_messages m
                          WHERE m.action_id = a.id AND m.message_kind = :kind
                      )
                    """
                ),
                {"logs_chat": logs_chat, "kind": kind},
            )

    # * The imported decisions are history, so their cases are closed
    # * once the decisions and their evidence are in place. A case is
    # * opened first and closed afterwards: the guard of the table only
    # * lets a new case start as an open investigation, and a closed
    # * case does not take evidence anymore.
    for source in ("bans", "mutes", "warns", "kicks"):
        bind.execute(
            text(
                """
                UPDATE moderation_cases c
                SET status = 'resolved',
                    closed_by_user_id = c.opened_by_user_id,
                    resolved_at = c.created_at,
                    updated_at = c.created_at
                WHERE c.metadata ->> 'legacy_table' = :source
                  AND c.status = 'open'
                """
            ),
            {"source": source},
        )


def _drop_shifted_runtime_tables(bind) -> None:
    """Replace the runtime tables whose shape the migration cannot keep.

    The MTProto session table predates the Alembic migrations on some
    deployments: it stored the session blob in a ``data`` column, while
    the declared schema spreads it over ``value``, ``access_hash``, and
    ``type``. The old table cannot be widened in place without losing
    the rows the lease functions read, and it holds nothing but a
    session the bot can obtain again, so it is replaced instead.
    """
    bind.execute(
        text(
            """
            DO $do$
            BEGIN
                IF to_regclass('mtproto_state') IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM information_schema.columns
                       WHERE table_schema = current_schema()
                         AND table_name = 'mtproto_state'
                         AND column_name = 'value'
                   )
                THEN
                    EXECUTE 'DROP TABLE mtproto_state CASCADE';
                END IF;
            END
            $do$
            """
        )
    )


def _rename_legacy_table(bind, legacy: str, renamed: str) -> None:
    """Rename a legacy table and the constraints it carries.

    The constraint names live in the schema, not in the table, so a
    renamed table still holds the names the new table needs.
    """
    bind.execute(text(f"ALTER TABLE IF EXISTS {legacy} RENAME TO {renamed}"))
    bind.execute(
        text(
            f"""
            DO $do$
            DECLARE
                constraint_row record;
            BEGIN
                FOR constraint_row IN
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = current_schema()
                      AND t.relname = '{renamed}'
                LOOP
                    EXECUTE 'ALTER TABLE {renamed} RENAME CONSTRAINT '
                        || quote_ident(constraint_row.conname) || ' TO '
                        || quote_ident('legacy_' || constraint_row.conname);
                END LOOP;
            END
            $do$
            """
        )
    )


def upgrade() -> None:
    """Create the community schema and move the history into it."""
    bind = op.get_bind()

    # * The legacy tables that share their name with a new table are
    # * renamed first, so the new table can be created.
    for legacy, renamed in _RENAMED_LEGACY_TABLES:
        _rename_legacy_table(bind, legacy, renamed)

    _drop_shifted_runtime_tables(bind)

    metadata.create_all(bind, checkfirst=True)

    # * The views, the functions, the triggers, the policies, and the
    # * reference data come before the import: the import writes
    # * through the same guards the application does, and the role
    # * catalog has to exist before a role can be assigned.
    apply_schema(bind)

    _import_legacy_data(bind)

    for table in _DROPPED_LEGACY_TABLES:
        bind.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


def downgrade() -> None:
    """Remove the community schema.

    The history of the replaced tables is not restored: the revision
    moved it into the new tables and dropped the old ones.
    """
    bind = op.get_bind()
    for table in reversed(metadata.sorted_tables):
        bind.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
