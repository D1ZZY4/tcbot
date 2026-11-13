# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role, permission, and staff assignment tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, enum_check, metadata

# * The roles the community knows. A role is a named bundle of
# * permissions, and the priority orders the staff hierarchy.
role_definitions = Table(
    "role_definitions",
    metadata,
    Column("role_key", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("priority", SmallInteger, nullable=False, server_default="0"),
    Column("is_system", Boolean, nullable=False, server_default=text("false")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("role_key"),
    CheckConstraint("role_key ~ '^[a-z][a-z0-9_]*$'", name="ck_role_definitions_key"),
)

# * The permission catalog. The resource namespace always matches the
# * permission key, so the two can never drift apart.
permission_definitions = Table(
    "permission_definitions",
    metadata,
    Column("permission_key", Text, nullable=False),
    Column("resource", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("permission_key"),
    CheckConstraint(
        "permission_key ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'",
        name="ck_permission_definitions_key",
    ),
    CheckConstraint(
        "btrim(description) <> ''", name="ck_permission_definitions_description"
    ),
)

Index("ix_permission_definitions_resource", permission_definitions.c.resource)

# * Which role holds which permission.
role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_key", Text, nullable=False),
    Column("permission_key", Text, nullable=False),
    PrimaryKeyConstraint("role_key", "permission_key"),
    ForeignKeyConstraint(
        ["role_key"],
        ["role_definitions.role_key"],
        name="fk_role_permissions_role",
    ),
    ForeignKeyConstraint(
        ["permission_key"],
        ["permission_definitions.permission_key"],
        name="fk_role_permissions_permission",
    ),
)

Index("ix_role_permissions_permission", role_permissions.c.permission_key)

# * The staff assignment. A demotion revokes the row, it never deletes
# * it, so the history of who held which role stays readable.
role_assignments = Table(
    "role_assignments",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("role_key", Text, nullable=False),
    Column("assigned_by_user_id", BigInteger, nullable=True),
    Column(
        "assigned_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    Column("status", Text, nullable=False, server_default="active"),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("revoked_by_user_id", BigInteger, nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["user_id"],
        ["telegram_users.user_id"],
        name="fk_role_assignments_user",
    ),
    ForeignKeyConstraint(
        ["assigned_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_role_assignments_assigned_by",
    ),
    ForeignKeyConstraint(
        ["revoked_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_role_assignments_revoked_by",
    ),
    ForeignKeyConstraint(
        ["role_key"],
        ["role_definitions.role_key"],
        name="fk_role_assignments_role",
    ),
    enum_check("ck_role_assignments_status", "status", "active", "revoked", "expired"),
)

Index("ix_role_assignments_user", role_assignments.c.user_id)
Index("ix_role_assignments_role", role_assignments.c.role_key)
Index("ix_role_assignments_status", role_assignments.c.status)
Index("ix_role_assignments_expires", role_assignments.c.expires_at)
# * A user holds one active role. The index is the guard that survives
# * a race: two concurrent promotions of the same user cannot both
# * land, whatever the application checks.
Index(
    "uq_role_assignments_active_user",
    role_assignments.c.user_id,
    unique=True,
    postgresql_where=text("status = 'active'"),
)
# * The community holds one active owner. Every active owner carries
# * the same role key, so the key is unique among them.
Index(
    "uq_role_assignments_active_owner",
    role_assignments.c.role_key,
    unique=True,
    postgresql_where=text("status = 'active' AND role_key = 'owner'"),
)

# * A request to promote somebody, and the decision taken on it.
promotion_requests = Table(
    "promotion_requests",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("request_id", Text, nullable=False),
    Column("target_user_id", BigInteger, nullable=False),
    Column("requested_role_key", Text, nullable=False),
    Column("requested_by_user_id", BigInteger, nullable=False),
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
        ["target_user_id"],
        ["telegram_users.user_id"],
        name="fk_promotion_requests_target",
    ),
    ForeignKeyConstraint(
        ["requested_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_promotion_requests_requested_by",
    ),
    ForeignKeyConstraint(
        ["resolved_by_user_id"],
        ["telegram_users.user_id"],
        name="fk_promotion_requests_resolved_by",
    ),
    ForeignKeyConstraint(
        ["requested_role_key"],
        ["role_definitions.role_key"],
        name="fk_promotion_requests_role",
    ),
    UniqueConstraint("request_id", name="uq_promotion_requests_request_id"),
    CheckConstraint("btrim(request_id) <> ''", name="ck_promotion_requests_request_id"),
    enum_check(
        "ck_promotion_requests_status",
        "status",
        "pending",
        "approved",
        "rejected",
        "cancelled",
    ),
)

Index("ix_promotion_requests_status", promotion_requests.c.status)
Index("ix_promotion_requests_target", promotion_requests.c.target_user_id)
# * One open request per target: two moderators asking for the same
# * promotion collapse into one queue entry.
Index(
    "uq_promotion_requests_pending_target",
    promotion_requests.c.target_user_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)
