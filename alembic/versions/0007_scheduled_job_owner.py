# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Record which job registry rows pg_cron is expected to fire.

The drift report compared every registry row with ``cron.job``, so the
application-owned jobs (retention, account erasure, the drift audit
itself) were reported as missing whenever pg_cron was active. The owner
column separates the two populations.

Revision ID: 0007_scheduled_job_owner
Revises: 0006_notification_tasks
Create Date: 2026-11-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op
from tcbot.database.schema import apply_schema

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection

revision: str = "0007_scheduled_job_owner"
down_revision: str | None = "0006_notification_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE: str = "scheduled_jobs"
_OWNER_CHECK: str = "ck_scheduled_jobs_owner"


def _column_names(bind: Connection) -> set[str]:
    names: set[str] = set()
    for column in sa.inspect(bind).get_columns(_TABLE):
        name = column.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _check_names(bind: Connection) -> set[str]:
    names: set[str] = set()
    for check in sa.inspect(bind).get_check_constraints(_TABLE):
        name = check.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def upgrade() -> None:
    """Add the owner marker and reapply the registry-aware SQL objects."""
    bind = op.get_bind()
    if "job_owner" not in _column_names(bind):
        op.add_column(
            _TABLE,
            sa.Column(
                "job_owner",
                sa.Text(),
                nullable=False,
                server_default="application",
            ),
        )
    if _OWNER_CHECK not in _check_names(bind):
        op.create_check_constraint(
            _OWNER_CHECK,
            _TABLE,
            "job_owner IN ('application', 'pg_cron')",
        )
    # * The drift function filters on the new column and the seed writes it,
    # * so both have to be reapplied after the column exists.
    apply_schema(bind)


def downgrade() -> None:
    """Leave the schema in place.

    The drift function and the registry seed name the ownership column, and
    the previous definitions are not versioned. Dropping the column would
    leave a broken function behind, so the revision is intentionally not
    reversed.
    """
