# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Table definitions for the TCF Bot PostgreSQL schema."""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

# * One metadata object owns every table, so Alembic autogenerate and the
# * runtime schema check read the same definitions.
metadata = MetaData()

# * Timestamps are stored as timezone-aware values. The application works
# * in UTC end to end (see tcbot.utils.time_and_date), so every column
# * carries the same zone.
_UTC_NOW = text("now()")


# ───────────────────────────── Bans ──────────────────────────────── #
# * A federation ban is not scoped to one group: it applies to every
# * connected group, so the table keys on the banned user.
bans = Table(
    "bans",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ban_id", Text, nullable=False),
    Column("banned_user_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False, server_default=""),
    Column("admin_user_id", BigInteger, nullable=False, server_default="0"),
    Column("proof_message_id", BigInteger, nullable=True),
    Column("log_message_id", BigInteger, nullable=True),
    Column("previous_proof_message_id", BigInteger, nullable=True),
    Column("previous_log_message_id", BigInteger, nullable=True),
    Column(
        "timestamp", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
    Column("updated_timestamp", DateTime(timezone=True), nullable=True),
    Column("until_date", DateTime(timezone=True), nullable=True),
    Column("duration_str", Text, nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("update_count", Integer, nullable=False, server_default="0"),
    Column("review_message_id", BigInteger, nullable=True),
    Column("review_timestamp", DateTime(timezone=True), nullable=True),
    Column("appeal_log_msg_id", BigInteger, nullable=True),
    Column("appeal_submitted_at", DateTime(timezone=True), nullable=True),
    Column("appeal_link", Text, nullable=True),
    Column("rejected_by_id", BigInteger, nullable=True),
    Column("rejected_by_name", Text, nullable=True),
    Column("rejected_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("ban_id", name="uq_bans_ban_id"),
)

# * One active ban per user, enforced by the database. Two moderators
# * reaching the warn threshold at the same moment must not be able to
# * store two records, or the profile and the appeal link would disagree
# * on which ban is real.
Index(
    "uq_bans_active_user",
    bans.c.banned_user_id,
    unique=True,
    postgresql_where=text("is_active"),
)
# * get_active_ban() filter plus its newest-first tie-break.
Index(
    "ix_bans_user_active",
    bans.c.banned_user_id,
    bans.c.is_active,
    bans.c.timestamp.desc(),
    bans.c.ban_id.desc(),
)
Index("ix_bans_active_user", bans.c.is_active, bans.c.banned_user_id)
Index(
    "ix_bans_active_time",
    bans.c.is_active,
    bans.c.timestamp.desc(),
    bans.c.ban_id.desc(),
)
Index(
    "ix_bans_user_time",
    bans.c.banned_user_id,
    bans.c.timestamp.desc(),
    bans.c.ban_id.desc(),
)
Index(
    "ix_bans_user_appeal",
    bans.c.banned_user_id,
    bans.c.appeal_log_msg_id,
    postgresql_where=text("appeal_log_msg_id IS NOT NULL"),
)


# ─────────────────────────── Audit trails ───────────────────────── #
# * Kick, mute and warn history are append-only audit records. They are
# * never deleted and they stay scoped to the group that produced them.
kicks = Table(
    "kicks",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False, server_default=""),
    Column("admin_id", BigInteger, nullable=False, server_default="0"),
    Column(
        "timestamp", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
)

Index("ix_kicks_user_time", kicks.c.user_id, kicks.c.timestamp.desc())
Index("ix_kicks_chat_id", kicks.c.chat_id)

mutes = Table(
    "mutes",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False, server_default=""),
    Column("admin_id", BigInteger, nullable=False, server_default="0"),
    Column(
        "timestamp", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
    Column("duration_secs", Integer, nullable=True),
)

Index("ix_mutes_user_time", mutes.c.user_id, mutes.c.timestamp.desc())
Index("ix_mutes_chat_id", mutes.c.chat_id)

warns = Table(
    "warns",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("reason", Text, nullable=False, server_default=""),
    Column("admin_id", BigInteger, nullable=False, server_default="0"),
    Column(
        "timestamp", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
)

# * The per-group warning history and the cross-group listing.
Index(
    "ix_warns_user_chat_time",
    warns.c.user_id,
    warns.c.chat_id,
    warns.c.timestamp.desc(),
)
Index("ix_warns_user_time", warns.c.user_id, warns.c.timestamp.desc())
# * The expiry sweep deletes on the timestamp alone.
Index("ix_warns_time", warns.c.timestamp)
# * The group migration repoints the chat id on every history row.
Index("ix_warns_chat_id", warns.c.chat_id)

# * The running warning total per user and group. The row is the counter:
# * a missing row means no warnings.
warn_counts = Table(
    "warn_counts",
    metadata,
    Column("user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("count", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
    PrimaryKeyConstraint("user_id", "chat_id"),
)

# * The warning-group listing filters on the user and sorts by recency.
Index(
    "ix_warn_counts_user_count_time",
    warn_counts.c.user_id,
    warn_counts.c.count,
    warn_counts.c.updated_at.desc(),
)
# * The expiry sweep deletes on the update timestamp alone.
Index("ix_warn_counts_updated_at", warn_counts.c.updated_at)
# * The group migration repoints the chat id on every counter row.
Index("ix_warn_counts_chat_id", warn_counts.c.chat_id)


# ───────────────────── Federation-wide enforcement ──────────────── #
# * The live mute state, one row per muted user. Unlike the audit trail
# * above this is federation-wide and has no chat scope: the mute is
# * re-applied to every connected group.
active_mutes = Table(
    "active_mutes",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("until_date", DateTime(timezone=True), nullable=True),
    Column(
        "timestamp", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
)

Index("ix_active_mutes_until", active_mutes.c.until_date)


# ─────────────────────────── Member cache ────────────────────────── #
# * Cached user profiles. The lowercase mirrors back the case-sensitive
# * prefix search, which is the only shape PostgreSQL can serve from an
# * index.
member_cache = Table(
    "member_cache",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=True),
    Column("last_name", Text, nullable=True),
    Column("first_name_lower", Text, nullable=True),
    Column("username_lower", Text, nullable=True),
    Column("commit_date", DateTime(timezone=True), nullable=True),
    Column(
        "last_updated", DateTime(timezone=True), nullable=False, server_default=_UTC_NOW
    ),
)

# * text_pattern_ops makes the prefix scan work under a non-C collation.
# * The default text_ops opclass can only serve a prefix scan when the
# * database collation is C, and the deployment database is not. Without
# * the opclass the name search degrades to a sequential scan.
Index(
    "ix_member_cache_username_lower",
    member_cache.c.username_lower,
    member_cache.c.user_id,
    postgresql_ops={"username_lower": "text_pattern_ops"},
)
Index(
    "ix_member_cache_first_name_lower",
    member_cache.c.first_name_lower,
    member_cache.c.user_id,
    postgresql_ops={"first_name_lower": "text_pattern_ops"},
)
# * A pattern opclass only provides the pattern comparison operators, so
# * the index above cannot serve an ORDER BY on the same column. The
# * paged user list sorts on it, and without a default-opclass index the
# * planner sorts the whole table on every page turn.
Index(
    "ix_member_cache_username_lower_sort",
    member_cache.c.username_lower,
    member_cache.c.user_id,
)
Index(
    "ix_member_cache_first_name_lower_sort",
    member_cache.c.first_name_lower,
    member_cache.c.user_id,
)
Index(
    "ix_member_cache_last_updated",
    member_cache.c.last_updated.desc(),
    member_cache.c.user_id,
)


# ───────────────────────── User preferences ──────────────────────── #
# * Per-user preferences live in their own table so preference-only rows
# * never inflate the member cache counts or appear in user listings.
user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("locale", Text, nullable=True),
)


# ───────────────────────────── Roles ─────────────────────────────── #
tc_owners = Table(
    "tc_owners",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
)

tc_admins = Table(
    "tc_admins",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("promoted_by", BigInteger, nullable=True),
    Column("promoted_date", DateTime(timezone=True), nullable=True),
)

tc_roles = Table(
    "tc_roles",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("role", Text, nullable=False),
    Column("assigned_by", BigInteger, nullable=True),
    Column("assigned_at", DateTime(timezone=True), nullable=True),
)

Index("ix_tc_roles_role", tc_roles.c.role)


# ───────────────────────────── Groups ────────────────────────────── #
federated_groups = Table(
    "federated_groups",
    metadata,
    Column("chat_id", BigInteger, primary_key=True, autoincrement=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("added_by", BigInteger, nullable=True),
    Column("added_date", DateTime(timezone=True), nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("locale", Text, nullable=True),
)

Index("ix_groups_active", federated_groups.c.is_active)

pending_joins = Table(
    "pending_joins",
    metadata,
    Column("chat_id", BigInteger, primary_key=True, autoincrement=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("owner_id", BigInteger, nullable=True),
    Column("message_id", BigInteger, nullable=True),
    Column("added_date", DateTime(timezone=True), nullable=True),
)


# ─────────────────────── Promotion requests ──────────────────────── #
promotion_requests = Table(
    "promotion_requests",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("request_id", Text, nullable=False),
    Column("target_id", BigInteger, nullable=False),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=False, server_default=""),
    Column("promoted_by", BigInteger, nullable=False, server_default="0"),
    Column("status", Text, nullable=False, server_default="pending"),
    Column(
        "requested_date",
        DateTime(timezone=True),
        nullable=False,
        server_default=_UTC_NOW,
    ),
    Column("resolved_date", DateTime(timezone=True), nullable=True),
    Column("resolved_by", BigInteger, nullable=True),
    UniqueConstraint("request_id", name="uq_promotion_requests_request_id"),
)

# * One pending request per user: concurrent promotes collapse into a
# * single queue entry instead of duplicates.
Index(
    "uq_promotion_requests_pending",
    promotion_requests.c.target_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)
Index(
    "ix_promotion_requests_status_date",
    promotion_requests.c.status,
    promotion_requests.c.requested_date,
)
Index(
    "ix_promotion_requests_target_status",
    promotion_requests.c.target_id,
    promotion_requests.c.status,
)


# ────────────────────────── MTProto state ────────────────────────── #
# * The Kurigram session state. One row per key, scoped by the session
# * namespace: ``<ns>:kv:<name>`` scalars, ``<ns>:peer:<peer_id>`` peers
# * and ``<ns>:ustate:<id>`` update states.
# *
# * The three record kinds share one table and are told apart by the key
# * prefix, so the columns of the other kinds stay NULL. The scalar value
# * is stored as msgpack because the session keys hold opaque Python
# * objects (the authorization key is raw bytes).
mtproto_state = Table(
    "mtproto_state",
    metadata,
    Column("id", Text, primary_key=True),
    Column("value", LargeBinary, nullable=True),
    Column("access_hash", BigInteger, nullable=True),
    Column("type", Text, nullable=True),
    Column("usernames", ARRAY(Text), nullable=True),
    Column("phone_number", Text, nullable=True),
    Column("updated_on", BigInteger, nullable=True),
    Column("pts", Integer, nullable=True),
    Column("qts", Integer, nullable=True),
    Column("date", Integer, nullable=True),
    Column("seq", Integer, nullable=True),
    # * The single-owner lease lives in this table too: the holder and
    # * the epoch second its lease expires at are the only fields a
    # * lease row carries. The primary key serves the lease lookup.
    Column("owner", Text, nullable=True),
    Column("expires_at", BigInteger, nullable=True),
)

# * The update states are read oldest-first by the session worker.
Index("ix_mtproto_state_date", mtproto_state.c.date)
# * A GIN index serves the containment and equality lookups the peer
# * username search needs over the name array.
Index(
    "ix_mtproto_state_usernames",
    mtproto_state.c.usernames,
    postgresql_using="gin",
)
# * The row key carries the session namespace as a prefix, so the peer
# * and update-state lookups match on a prefix. The default text opclass
# * can only serve a prefix scan under a C collation, and the deployment
# * database is not C, so the pattern opclass is required.
Index(
    "ix_mtproto_state_id_pattern",
    mtproto_state.c.id,
    postgresql_ops={"id": "text_pattern_ops"},
)
Index(
    "ix_mtproto_state_phone_number",
    mtproto_state.c.phone_number,
    postgresql_where=text("phone_number IS NOT NULL"),
)
