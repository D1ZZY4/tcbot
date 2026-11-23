# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Add the promotion-request expiry.

A pending promotion request that is never decided blocks every later
request for the same target through the partial unique index. The column
carries the absolute deadline, and the status check learns the ``expired``
terminal state the sweep writes.

Revision 0003 creates its tables from the current metadata, so this
revision tolerates a fresh database that already carries the column and
the new status value.

Revision ID: 0005_promotion_request_expiry
Revises: 0004_reapply_schema_objects
Create Date: 2026-11-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection


revision: str = "0005_promotion_request_expiry"
down_revision: str | None = "0004_reapply_schema_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE: str = "promotion_requests"
_STATUS_CHECK: str = "ck_promotion_requests_status"
_EXPIRY_CHECK: str = "ck_promotion_requests_expiry"
_EXPIRY_INDEX: str = "ix_promotion_requests_expiry"
_OLD_STATUS: str = "status IN ('pending', 'approved', 'rejected', 'cancelled')"
_NEW_STATUS: str = (
    "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')"
)


def _column_names(bind: Connection) -> set[str]:
    names: set[str] = set()
    for column in sa.inspect(bind).get_columns(_TABLE):
        name = column.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _check_sql(bind: Connection, name: str) -> str | None:
    for check in sa.inspect(bind).get_check_constraints(_TABLE):
        if check.get("name") == name:
            return str(check.get("sqltext") or "")
    return None


def _index_names(bind: Connection) -> set[str]:
    names: set[str] = set()
    for index in sa.inspect(bind).get_indexes(_TABLE):
        name = index.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def upgrade() -> None:
    """Add the expiry column, its check, the status value, and the index."""
    bind = op.get_bind()
    if "expires_at" not in _column_names(bind):
        op.add_column(
            _TABLE,
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if _check_sql(bind, _EXPIRY_CHECK) is None:
        op.create_check_constraint(
            _EXPIRY_CHECK,
            _TABLE,
            "expires_at IS NULL OR expires_at > requested_at",
        )
    status_sql = _check_sql(bind, _STATUS_CHECK)
    if status_sql is not None and "expired" not in status_sql:
        op.drop_constraint(_STATUS_CHECK, _TABLE, type_="check")
        op.create_check_constraint(_STATUS_CHECK, _TABLE, _NEW_STATUS)
    if _EXPIRY_INDEX not in _index_names(bind):
        op.create_index(
            _EXPIRY_INDEX,
            _TABLE,
            ["status", "expires_at"],
        )
    # * Revision 0006 reapplies the SQL objects after both new tables exist;
    # * doing it here would touch the notification table before its revision
    # * creates it on a database that is upgrading from 0004.


def downgrade() -> None:
    """Remove the expiry state and restore the four-state status check."""
    bind = op.get_bind()
    if _EXPIRY_INDEX in _index_names(bind):
        op.drop_index(_EXPIRY_INDEX, table_name=_TABLE)
    status_sql = _check_sql(bind, _STATUS_CHECK)
    if status_sql is not None and "expired" in status_sql:
        # * The narrow check validates existing rows when it is created, so
        # * requests the sweep already expired must first be folded into a
        # * terminal state the old check accepts. The lifecycle guard from
        # * 0004 rejects a status change on a resolved row, so suspend that
        # * one trigger; the downgrade transaction restores it on rollback.
        op.execute(
            "ALTER TABLE promotion_requests "
            "DISABLE TRIGGER trg_promotion_requests_lifecycle"
        )
        op.execute(
            sa.text(
                "UPDATE promotion_requests SET status = 'cancelled' "
                "WHERE status = 'expired'"
            )
        )
        op.execute(
            "ALTER TABLE promotion_requests "
            "ENABLE TRIGGER trg_promotion_requests_lifecycle"
        )
        op.drop_constraint(_STATUS_CHECK, _TABLE, type_="check")
        op.create_check_constraint(_STATUS_CHECK, _TABLE, _OLD_STATUS)
    if _check_sql(bind, _EXPIRY_CHECK) is not None:
        op.drop_constraint(_EXPIRY_CHECK, _TABLE, type_="check")
    if "expires_at" in _column_names(bind):
        op.drop_column(_TABLE, "expires_at")
