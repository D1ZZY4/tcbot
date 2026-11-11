# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Initial TCF Bot schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-11

The tables are generated from ``tcbot.database.base`` so the migration
and the runtime schema cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create every table and index."""
    op.create_table(
        "active_mutes",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "until_date",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_active_mutes_until", "active_mutes", ["until_date"], unique=False
    )
    op.create_table(
        "bans",
        sa.Column(
            "id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "ban_id",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "banned_user_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "admin_user_id",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "proof_message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "log_message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "previous_proof_message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "previous_log_message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_timestamp",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "until_date",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "duration_str",
            sa.Text(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "update_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "review_message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "review_timestamp",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "appeal_log_msg_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "appeal_submitted_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "appeal_link",
            sa.Text(),
        ),
        sa.Column(
            "rejected_by_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "rejected_by_name",
            sa.Text(),
        ),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
        ),
        sa.UniqueConstraint("ban_id", name="uq_bans_ban_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bans_active_time",
        "bans",
        ["is_active", sa.text("timestamp DESC"), sa.text("ban_id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_bans_active_user", "bans", ["is_active", "banned_user_id"], unique=False
    )
    op.create_index(
        "ix_bans_user_active",
        "bans",
        [
            "banned_user_id",
            "is_active",
            sa.text("timestamp DESC"),
            sa.text("ban_id DESC"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_bans_user_appeal",
        "bans",
        ["banned_user_id", "appeal_log_msg_id"],
        unique=False,
        postgresql_where=sa.text("appeal_log_msg_id IS NOT NULL"),
    )
    op.create_index(
        "ix_bans_user_time",
        "bans",
        ["banned_user_id", sa.text("timestamp DESC"), sa.text("ban_id DESC")],
        unique=False,
    )
    op.create_index(
        "uq_bans_active_user",
        "bans",
        ["banned_user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "federated_groups",
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "title",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "added_by",
            sa.BigInteger(),
        ),
        sa.Column(
            "added_date",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "locale",
            sa.Text(),
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index("ix_groups_active", "federated_groups", ["is_active"], unique=False)
    op.create_table(
        "kicks",
        sa.Column(
            "id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kicks_chat_id", "kicks", ["chat_id"], unique=False)
    op.create_index(
        "ix_kicks_user_time",
        "kicks",
        ["user_id", sa.text("timestamp DESC")],
        unique=False,
    )
    op.create_table(
        "member_cache",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "username",
            sa.Text(),
        ),
        sa.Column(
            "first_name",
            sa.Text(),
        ),
        sa.Column(
            "last_name",
            sa.Text(),
        ),
        sa.Column(
            "first_name_lower",
            sa.Text(),
        ),
        sa.Column(
            "username_lower",
            sa.Text(),
        ),
        sa.Column(
            "commit_date",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_member_cache_first_name_lower",
        "member_cache",
        ["first_name_lower", "user_id"],
        unique=False,
        postgresql_ops={"first_name_lower": "text_pattern_ops"},
    )
    op.create_index(
        "ix_member_cache_last_updated",
        "member_cache",
        [sa.text("last_updated DESC"), "user_id"],
        unique=False,
    )
    op.create_index(
        "ix_member_cache_username_lower",
        "member_cache",
        ["username_lower", "user_id"],
        unique=False,
        postgresql_ops={"username_lower": "text_pattern_ops"},
    )
    op.create_table(
        "mtproto_state",
        sa.Column(
            "id",
            sa.Text(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "value",
            sa.LargeBinary(),
        ),
        sa.Column(
            "access_hash",
            sa.BigInteger(),
        ),
        sa.Column(
            "type",
            sa.Text(),
        ),
        sa.Column(
            "usernames",
            sa.ARRAY(sa.Text()),
        ),
        sa.Column(
            "phone_number",
            sa.Text(),
        ),
        sa.Column(
            "updated_on",
            sa.BigInteger(),
        ),
        sa.Column(
            "pts",
            sa.Integer(),
        ),
        sa.Column(
            "qts",
            sa.Integer(),
        ),
        sa.Column(
            "date",
            sa.Integer(),
        ),
        sa.Column(
            "seq",
            sa.Integer(),
        ),
        sa.Column(
            "owner",
            sa.Text(),
        ),
        sa.Column(
            "expires_at",
            sa.BigInteger(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mtproto_state_date", "mtproto_state", ["date"], unique=False)
    op.create_index(
        "ix_mtproto_state_id_pattern",
        "mtproto_state",
        ["id"],
        unique=False,
        postgresql_ops={"id": "text_pattern_ops"},
    )
    op.create_index(
        "ix_mtproto_state_phone_number",
        "mtproto_state",
        ["phone_number"],
        unique=False,
        postgresql_where=sa.text("phone_number IS NOT NULL"),
    )
    op.create_index(
        "ix_mtproto_state_usernames",
        "mtproto_state",
        ["usernames"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "mutes",
        sa.Column(
            "id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "duration_secs",
            sa.Integer(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mutes_chat_id", "mutes", ["chat_id"], unique=False)
    op.create_index(
        "ix_mutes_user_time",
        "mutes",
        ["user_id", sa.text("timestamp DESC")],
        unique=False,
    )
    op.create_table(
        "pending_joins",
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "title",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "message_id",
            sa.BigInteger(),
        ),
        sa.Column(
            "added_date",
            sa.DateTime(timezone=True),
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "promotion_requests",
        sa.Column(
            "id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "request_id",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "username",
            sa.Text(),
        ),
        sa.Column(
            "first_name",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "promoted_by",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "requested_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "resolved_date",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "resolved_by",
            sa.BigInteger(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_promotion_requests_request_id"),
    )
    op.create_index(
        "ix_promotion_requests_status_date",
        "promotion_requests",
        ["status", "requested_date"],
        unique=False,
    )
    op.create_index(
        "ix_promotion_requests_target_status",
        "promotion_requests",
        ["target_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_promotion_requests_pending",
        "promotion_requests",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "tc_admins",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "promoted_by",
            sa.BigInteger(),
        ),
        sa.Column(
            "promoted_date",
            sa.DateTime(timezone=True),
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "tc_owners",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "tc_roles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "role",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "assigned_by",
            sa.BigInteger(),
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_tc_roles_role", "tc_roles", ["role"], unique=False)
    op.create_table(
        "user_settings",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "locale",
            sa.Text(),
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "warn_counts",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "chat_id"),
    )
    op.create_index("ix_warn_counts_chat_id", "warn_counts", ["chat_id"], unique=False)
    op.create_index(
        "ix_warn_counts_updated_at", "warn_counts", ["updated_at"], unique=False
    )
    op.create_index(
        "ix_warn_counts_user_count_time",
        "warn_counts",
        ["user_id", "count", sa.text("updated_at DESC")],
        unique=False,
    )
    op.create_table(
        "warns",
        sa.Column(
            "id",
            sa.BigInteger(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_warns_chat_id", "warns", ["chat_id"], unique=False)
    op.create_index("ix_warns_time", "warns", ["timestamp"], unique=False)
    op.create_index(
        "ix_warns_user_chat_time",
        "warns",
        ["user_id", "chat_id", sa.text("timestamp DESC")],
        unique=False,
    )
    op.create_index(
        "ix_warns_user_time",
        "warns",
        ["user_id", sa.text("timestamp DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Drop every index and table."""
    op.drop_index("ix_warns_chat_id", table_name="warns")
    op.drop_index("ix_warns_time", table_name="warns")
    op.drop_index("ix_warns_user_chat_time", table_name="warns")
    op.drop_index("ix_warns_user_time", table_name="warns")
    op.drop_table("warns")
    op.drop_index("ix_warn_counts_chat_id", table_name="warn_counts")
    op.drop_index("ix_warn_counts_updated_at", table_name="warn_counts")
    op.drop_index("ix_warn_counts_user_count_time", table_name="warn_counts")
    op.drop_table("warn_counts")
    op.drop_table("user_settings")
    op.drop_index("ix_tc_roles_role", table_name="tc_roles")
    op.drop_table("tc_roles")
    op.drop_table("tc_owners")
    op.drop_table("tc_admins")
    op.drop_index("ix_promotion_requests_status_date", table_name="promotion_requests")
    op.drop_index(
        "ix_promotion_requests_target_status", table_name="promotion_requests"
    )
    op.drop_index("uq_promotion_requests_pending", table_name="promotion_requests")
    op.drop_table("promotion_requests")
    op.drop_table("pending_joins")
    op.drop_index("ix_mutes_chat_id", table_name="mutes")
    op.drop_index("ix_mutes_user_time", table_name="mutes")
    op.drop_table("mutes")
    op.drop_index("ix_mtproto_state_date", table_name="mtproto_state")
    op.drop_index("ix_mtproto_state_id_pattern", table_name="mtproto_state")
    op.drop_index("ix_mtproto_state_phone_number", table_name="mtproto_state")
    op.drop_index("ix_mtproto_state_usernames", table_name="mtproto_state")
    op.drop_table("mtproto_state")
    op.drop_index("ix_member_cache_first_name_lower", table_name="member_cache")
    op.drop_index("ix_member_cache_last_updated", table_name="member_cache")
    op.drop_index("ix_member_cache_username_lower", table_name="member_cache")
    op.drop_table("member_cache")
    op.drop_index("ix_kicks_chat_id", table_name="kicks")
    op.drop_index("ix_kicks_user_time", table_name="kicks")
    op.drop_table("kicks")
    op.drop_index("ix_groups_active", table_name="federated_groups")
    op.drop_table("federated_groups")
    op.drop_index("ix_bans_active_time", table_name="bans")
    op.drop_index("ix_bans_active_user", table_name="bans")
    op.drop_index("ix_bans_user_active", table_name="bans")
    op.drop_index("ix_bans_user_appeal", table_name="bans")
    op.drop_index("ix_bans_user_time", table_name="bans")
    op.drop_index("uq_bans_active_user", table_name="bans")
    op.drop_table("bans")
    op.drop_index("ix_active_mutes_until", table_name="active_mutes")
    op.drop_table("active_mutes")
