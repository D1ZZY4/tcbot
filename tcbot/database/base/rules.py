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
    func,
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
# * Two staff members must never open two drafts for the same set and locale.
Index(
    "uq_rule_set_versions_draft",
    rule_set_versions.c.rule_set_id,
    rule_set_versions.c.locale,
    unique=True,
    postgresql_where=text("status = 'draft'"),
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
    # * Category snapshots freeze the presentation of an old version even if
    # * the category catalogue is later renamed or reordered.
    Column("category_title", Text, nullable=True),
    Column("category_sort_order", Integer, nullable=True),
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

# * The category catalogue of one rule set. Staff may rename, reorder, and
# * add categories; item snapshots keep published versions unchanged.
rule_categories = Table(
    "rule_categories",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_id", BigInteger, nullable=False),
    Column("category_key", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("sort_order", Integer, nullable=False, server_default="100"),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_id"], ["rule_sets.id"], name="fk_rule_categories_rule_set"
    ),
    UniqueConstraint("rule_set_id", "category_key", name="uq_rule_categories_set_key"),
    CheckConstraint(
        "category_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_rule_categories_key"
    ),
    CheckConstraint("btrim(title) <> ''", name="ck_rule_categories_title"),
    CheckConstraint("sort_order >= 0", name="ck_rule_categories_sort_order"),
)

Index("ix_rule_categories_rule_set", rule_categories.c.rule_set_id)

# * The lock of one publish plus sync operation. No background owner exists:
# * a run lives only while a staff publish is in progress.
rule_publication_runs = Table(
    "rule_publication_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_id", BigInteger, nullable=False),
    Column("rule_set_version_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False, server_default="running"),
    Column(
        "started_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=False),
    Column("error", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_id"], ["rule_sets.id"], name="fk_rule_publication_runs_rule_set"
    ),
    ForeignKeyConstraint(
        ["rule_set_version_id"],
        ["rule_set_versions.id"],
        name="fk_rule_publication_runs_version",
    ),
    enum_check(
        "ck_rule_publication_runs_status",
        "status",
        "running",
        "completed",
        "partial",
        "failed",
    ),
)

Index("ix_rule_publication_runs_status", rule_publication_runs.c.status)
Index("ix_rule_publication_runs_lease", rule_publication_runs.c.lease_expires_at)
# * A live run excludes a second concurrent publish for the same set and chat.
Index(
    "uq_rule_publication_runs_active",
    rule_publication_runs.c.rule_set_id,
    rule_publication_runs.c.chat_id,
    unique=True,
    postgresql_where=text("status = 'running'"),
)

# * One channel message slot. The message id lives here so the database stays
# * the source of truth and a later publish can reconcile a failed or missing
# * channel message.
rule_publications = Table(
    "rule_publications",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("rule_set_id", BigInteger, nullable=False),
    Column("rule_set_version_id", BigInteger, nullable=False),
    Column("locale", Text, nullable=False, server_default="en-US"),
    Column("chat_id", BigInteger, nullable=False),
    Column("message_thread_id", BigInteger, nullable=True),
    Column("category_key", Text, nullable=False),
    Column("part_index", Integer, nullable=False, server_default="0"),
    Column("message_id", BigInteger, nullable=True),
    Column("content_hash", Text, nullable=True),
    Column("run_id", BigInteger, nullable=True),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("last_error", Text, nullable=True),
    Column("last_synced_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["rule_set_id"], ["rule_sets.id"], name="fk_rule_publications_rule_set"
    ),
    ForeignKeyConstraint(
        ["rule_set_version_id"],
        ["rule_set_versions.id"],
        name="fk_rule_publications_version",
    ),
    ForeignKeyConstraint(
        ["run_id"], ["rule_publication_runs.id"], name="fk_rule_publications_run"
    ),
    enum_check(
        "ck_rule_publications_status",
        "status",
        "pending",
        "synced",
        "failed",
        "missing",
        "retired",
        "deleted",
    ),
    CheckConstraint("part_index >= 0", name="ck_rule_publications_part_index"),
    CheckConstraint(
        "message_id IS NULL OR message_id > 0", name="ck_rule_publications_message_id"
    ),
    CheckConstraint(
        "message_thread_id IS NULL OR message_thread_id > 0",
        name="ck_rule_publications_thread_id",
    ),
)

Index(
    "ix_rule_publications_set_locale_status",
    rule_publications.c.rule_set_id,
    rule_publications.c.locale,
    rule_publications.c.status,
)
Index("ix_rule_publications_version", rule_publications.c.rule_set_version_id)
Index("ix_rule_publications_run", rule_publications.c.run_id)
# * NULL thread ids are distinct in a plain unique index, so coalesce them.
Index(
    "uq_rule_publications_slot",
    rule_publications.c.rule_set_id,
    rule_publications.c.locale,
    rule_publications.c.chat_id,
    func.coalesce(rule_publications.c.message_thread_id, 0),
    rule_publications.c.category_key,
    rule_publications.c.part_index,
    unique=True,
)
Index(
    "uq_rule_publications_message",
    rule_publications.c.chat_id,
    rule_publications.c.message_id,
    unique=True,
    postgresql_where=text("message_id IS NOT NULL"),
)
