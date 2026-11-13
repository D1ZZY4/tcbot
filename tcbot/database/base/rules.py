# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rule set, version, item, and acknowledgement tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from ._shared import EMPTY_OBJECT, UTC_NOW, enum_check, metadata

# * A named set of rules, either for the community or for one group.
rule_sets = Table(
    "rule_sets",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("scope_type", Text, nullable=False),
    Column("chat_id", BigInteger, nullable=True),
    Column("rule_set_key", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "requires_acknowledgement",
        Boolean,
        nullable=False,
        server_default=text("false"),
    ),
    Column("created_by_user_id", BigInteger, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["chat_id"],
        ["connected_chats.chat_id"],
        name="fk_rule_sets_chat",
    ),
    ForeignKeyConstraint(
        ["created_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_rule_sets_created_by",
    ),
    enum_check("ck_rule_sets_scope", "scope_type", "community", "chat"),
    CheckConstraint("rule_set_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_rule_sets_key"),
    CheckConstraint("btrim(name) <> ''", name="ck_rule_sets_name"),
    # * A community rule set has no chat, a chat rule set always has one.
    CheckConstraint(
        "(scope_type = 'community' AND chat_id IS NULL) "
        "OR (scope_type = 'chat' AND chat_id IS NOT NULL)",
        name="ck_rule_sets_scope_chat",
    ),
)

Index("ix_rule_sets_scope", rule_sets.c.scope_type)
Index("ix_rule_sets_chat", rule_sets.c.chat_id)

# * One version of a rule set in one locale. A published version is
# * immutable: a revision is a new draft.
rule_set_versions = Table(
    "rule_set_versions",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_id", BigInteger, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("locale", Text, nullable=False, server_default="en-US"),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("change_summary", Text, nullable=True),
    Column("created_by_user_id", BigInteger, nullable=True),
    Column("published_by_user_id", BigInteger, nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_id"],
        ["rule_sets.id"],
        name="fk_rule_set_versions_rule_set",
    ),
    ForeignKeyConstraint(
        ["created_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_rule_set_versions_created_by",
    ),
    ForeignKeyConstraint(
        ["published_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_rule_set_versions_published_by",
    ),
    UniqueConstraint(
        "rule_set_id", "locale", "version_number", name="uq_rule_set_versions_number"
    ),
    CheckConstraint("version_number > 0", name="ck_rule_set_versions_number"),
    enum_check(
        "ck_rule_set_versions_status",
        "status",
        "draft",
        "published",
        "superseded",
        "archived",
    ),
)

Index("ix_rule_set_versions_rule_set", rule_set_versions.c.rule_set_id)
Index("ix_rule_set_versions_status", rule_set_versions.c.status)
# * Only one published version per rule set and locale.
Index(
    "uq_rule_set_versions_published",
    rule_set_versions.c.rule_set_id,
    rule_set_versions.c.locale,
    unique=True,
    postgresql_where=text("status = 'published'"),
)

# * One rule inside a version. The search vector backs the rule lookup.
rule_items = Table(
    "rule_items",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_version_id", BigInteger, nullable=False),
    Column("rule_key", Text, nullable=False),
    Column("category_key", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("content_format", Text, nullable=False, server_default="plain_text"),
    Column("sort_order", Integer, nullable=False, server_default="100"),
    Column("is_mandatory", Boolean, nullable=False, server_default=text("true")),
    Column("reference_url", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "search_vector",
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, "
            "(COALESCE(title, ''::text) || ' '::text) || COALESCE(body, ''::text))",
            persisted=True,
        ),
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_version_id"],
        ["rule_set_versions.id"],
        name="fk_rule_items_rule_set_version",
    ),
    UniqueConstraint(
        "rule_set_version_id", "rule_key", name="uq_rule_items_version_key"
    ),
    CheckConstraint(
        "rule_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_rule_items_rule_key"
    ),
    CheckConstraint(
        "category_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_rule_items_category_key"
    ),
    CheckConstraint("btrim(title) <> ''", name="ck_rule_items_title"),
    CheckConstraint("btrim(body) <> ''", name="ck_rule_items_body"),
    enum_check(
        "ck_rule_items_content_format", "content_format", "plain_text", "markdown"
    ),
    CheckConstraint("sort_order >= 0", name="ck_rule_items_sort_order"),
)

Index("ix_rule_items_version", rule_items.c.rule_set_version_id)
Index("ix_rule_items_search", rule_items.c.search_vector, postgresql_using="gin")

# * The proof that a user accepted one exact rule version.
rule_acknowledgements = Table(
    "rule_acknowledgements",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_version_id", BigInteger, nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("context_chat_id", BigInteger, nullable=True),
    Column(
        "acknowledgement_method", Text, nullable=False, server_default="inline_button"
    ),
    Column("telegram_message_id", BigInteger, nullable=True),
    Column(
        "acknowledged_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
    ),
    Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_version_id"],
        ["rule_set_versions.id"],
        name="fk_rule_acknowledgements_version",
    ),
    ForeignKeyConstraint(
        ["user_id"],
        ["telegram_users.user_id"],
        name="fk_rule_acknowledgements_user",
    ),
    ForeignKeyConstraint(
        ["context_chat_id"],
        ["telegram_chats.chat_id"],
        name="fk_rule_acknowledgements_context_chat",
    ),
    UniqueConstraint(
        "rule_set_version_id", "user_id", name="uq_rule_acknowledgements_version_user"
    ),
    enum_check(
        "ck_rule_acknowledgements_method",
        "acknowledgement_method",
        "inline_button",
        "command",
        "join_gate",
        "admin_recorded",
        "api",
    ),
)

Index("ix_rule_acknowledgements_user", rule_acknowledgements.c.user_id)
Index("ix_rule_acknowledgements_context_chat", rule_acknowledgements.c.context_chat_id)
