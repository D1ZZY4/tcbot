# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Telegram identity registry and the managed group registry."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, enum_check, metadata

# * The canonical identity of every Telegram user the bot has seen. The
# * numeric id is the identity: a username can change or disappear.
telegram_users = Table(
    "telegram_users",
    metadata,
    Column("user_id", BigInteger, nullable=False, autoincrement=False),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=True),
    Column("last_name", Text, nullable=True),
    Column("language_code", Text, nullable=True),
    Column("is_bot", Boolean, nullable=False, server_default=text("false")),
    Column("is_premium", Boolean, nullable=False, server_default=text("false")),
    Column(
        "first_seen_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("erased_at", DateTime(timezone=True), nullable=True),
    Column("erasure_reason", Text, nullable=True),
    PrimaryKeyConstraint("user_id"),
)

Index("ix_telegram_users_username", telegram_users.c.username)
Index("ix_telegram_users_first_name", telegram_users.c.first_name)
Index("ix_telegram_users_last_seen", telegram_users.c.last_seen_at)
# * The name search runs a case-sensitive prefix query on the lowercase
# * form, because PostgreSQL cannot serve a case-insensitive match from
# * an index. text_pattern_ops makes the prefix a range scan instead of
# * a full table scan on every search.
Index(
    "ix_telegram_users_first_name_lower",
    func.lower(telegram_users.c.first_name).label("lower"),
    postgresql_ops={"lower": "text_pattern_ops"},
)
Index(
    "ix_telegram_users_first_name_lower_sort", func.lower(telegram_users.c.first_name)
)
Index(
    "ix_telegram_users_username_lower",
    func.lower(telegram_users.c.username).label("lower"),
    postgresql_ops={"lower": "text_pattern_ops"},
)
Index("ix_telegram_users_username_lower_sort", func.lower(telegram_users.c.username))

# * The canonical identity of every Telegram chat the bot has seen.
telegram_chats = Table(
    "telegram_chats",
    metadata,
    Column("chat_id", BigInteger, nullable=False, autoincrement=False),
    Column("chat_type", Text, nullable=False, server_default="unknown"),
    Column("title", Text, nullable=True),
    Column("username", Text, nullable=True),
    Column("description", Text, nullable=True),
    Column("is_forum", Boolean, nullable=False, server_default=text("false")),
    Column("linked_chat_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("chat_id"),
    enum_check(
        "ck_telegram_chats_chat_type",
        "chat_type",
        "private",
        "group",
        "supergroup",
        "channel",
        "unknown",
    ),
    # * A forum group points at the channel that carries its topics.
    # * The constraint is declared separately because the table cannot
    # * reference itself while it is being created.
    ForeignKeyConstraint(
        ["linked_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_telegram_chats_linked_chat",
    ),
)

Index("ix_telegram_chats_username", telegram_chats.c.username)
Index("ix_telegram_chats_chat_type", telegram_chats.c.chat_type)

# * The groups the community currently manages. A disconnected group
# * stays in the registry: the history refers to it.
connected_chats = Table(
    "connected_chats",
    metadata,
    Column("chat_id", BigInteger, nullable=False, autoincrement=False),
    Column("added_by_user_id", BigInteger, nullable=True),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    PrimaryKeyConstraint("chat_id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_connected_chats_chat",
    ),
    ForeignKeyConstraint(
        ["added_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_connected_chats_added_by",
    ),
)

Index("ix_connected_chats_active", connected_chats.c.is_active)
Index("ix_connected_chats_added_by", connected_chats.c.added_by_user_id)

# * A group asking to join the community, and the decision taken on it.
join_requests = Table(
    "join_requests",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("owner_user_id", BigInteger, nullable=True),
    Column("request_message_id", BigInteger, nullable=True),
    Column("status", Text, nullable=False, server_default="pending"),
    Column(
        "requested_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("resolved_by_user_id", BigInteger, nullable=True),
    Column("decision_note", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_join_requests_chat",
    ),
    ForeignKeyConstraint(
        ["owner_user_id"],
        ["telegram_users.user_id"],
        name="fk_join_requests_owner",
    ),
    ForeignKeyConstraint(
        ["resolved_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_join_requests_resolved_by",
    ),
    enum_check(
        "ck_join_requests_status",
        "status",
        "pending",
        "approved",
        "rejected",
        "cancelled",
    ),
)

Index("ix_join_requests_status", join_requests.c.status)
Index("ix_join_requests_chat", join_requests.c.chat_id)
# * One open request per chat: a second approval attempt must not create
# * a second row to decide on.
Index(
    "uq_join_requests_pending_chat",
    join_requests.c.chat_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)

# * The membership of a user in one group. Membership is per chat, so
# * it is not a property of the user.
chat_members = Table(
    "chat_members",
    metadata,
    Column("chat_id", BigInteger, nullable=False, autoincrement=False),
    Column("user_id", BigInteger, nullable=False, autoincrement=False),
    Column("status", Text, nullable=False, server_default="member"),
    Column("custom_title", Text, nullable=True),
    Column("joined_at", DateTime(timezone=True), nullable=True),
    Column("until_date", DateTime(timezone=True), nullable=True),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("chat_id", "user_id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_chat_members_chat",
    ),
    ForeignKeyConstraint(
        ["user_id"],
        ["telegram_users.user_id"],
        name="fk_chat_members_user",
    ),
    enum_check(
        "ck_chat_members_status",
        "status",
        "creator",
        "administrator",
        "member",
        "restricted",
        "left",
        "kicked",
    ),
)

Index("ix_chat_members_user", chat_members.c.user_id)
Index("ix_chat_members_last_seen", chat_members.c.last_seen_at)
