# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community profile table."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._shared import EMPTY_OBJECT, UTC_NOW, metadata

# * The community is a singleton: one row carries the display name and
# * the global defaults every group falls back to.
community_settings = Table(
    "community_settings",
    metadata,
    Column("singleton_key", Text, nullable=False, server_default="global"),
    Column("community", Text, nullable=True),
    Column("description", Text, nullable=True),
    Column("default_locale", Text, nullable=True),
    Column("timezone", Text, nullable=True),
    Column("settings", JSONB, nullable=False, server_default=EMPTY_OBJECT),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    ),
    PrimaryKeyConstraint("singleton_key"),
    CheckConstraint("singleton_key = 'global'", name="ck_community_settings_singleton"),
    CheckConstraint(
        "community IS NULL OR btrim(community) <> ''",
        name="ck_community_settings_community",
    ),
    CheckConstraint(
        "description IS NULL OR btrim(description) <> ''",
        name="ck_community_settings_description",
    ),
)
