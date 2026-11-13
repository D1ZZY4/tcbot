# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user and per-group configuration tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, metadata

# * Personal preferences. A user may pick a locale for direct messages
# * but never a weaker policy.
user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", BigInteger, nullable=False, autoincrement=False),
    Column("locale", Text, nullable=True),
    Column("timezone", Text, nullable=True),
    Column("preferences", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("user_id"),
    ForeignKeyConstraint(
        ["user_id"],
        ["telegram_users.user_id"],
        name="fk_user_settings_user",
    ),
)

# * The group configuration. The connected group registry holds no
# * settings: this table is the single source for them.
chat_settings = Table(
    "chat_settings",
    metadata,
    Column("chat_id", BigInteger, nullable=False, autoincrement=False),
    Column("locale", Text, nullable=True),
    Column("timezone", Text, nullable=True),
    Column("settings", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("chat_id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_chat_settings_chat",
    ),
)
