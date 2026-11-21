# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Publication run locks for rules publishing."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import rule_publication_runs
from tcbot.database.engine import db_call, fetch_all, fetch_one, run
from tcbot.utils.time_and_date import utc_now

DEFAULT_LEASE_SECONDS: int = 300


async def reclaim_expired() -> int:
    """Mark stale running runs as failed so a later publish can proceed."""
    return await db_call(
        lambda: run(
            rule_publication_runs.update()
            .where(
                rule_publication_runs.c.status == "running",
                rule_publication_runs.c.lease_expires_at < utc_now(),
            )
            .values(
                status="failed",
                finished_at=utc_now(),
                error="Lease expired before the publish finished",
            )
        )
    )


async def acquire(
    set_id: int, version_id: int, chat_id: int, *, lease: int = DEFAULT_LEASE_SECONDS
) -> int:
    """Acquire the single live run of one set and channel.

    A concurrent publish is refused by the partial unique index rather than
    waiting, so two operators cannot send channel messages at the same time.
    """
    rows = await db_call(
        lambda: fetch_all(
            pg_insert(rule_publication_runs)
            .values(
                rule_set_id=set_id,
                rule_set_version_id=version_id,
                chat_id=chat_id,
                status="running",
                started_at=utc_now(),
                lease_expires_at=utc_now() + timedelta(seconds=lease),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    rule_publication_runs.c.rule_set_id,
                    rule_publication_runs.c.chat_id,
                ],
                index_where=text("status = 'running'"),
            )
            .returning(rule_publication_runs.c.id)
        )
    )
    if not rows:
        raise RuntimeError("A rules publish is already running for this channel")
    return int(rows[0]["id"])


async def finish(run_id: int, status: str, *, error: str | None = None) -> None:
    """Close a run with a terminal status."""
    await db_call(
        lambda: run(
            rule_publication_runs.update()
            .where(rule_publication_runs.c.id == run_id)
            .values(status=status, finished_at=utc_now(), error=error)
        )
    )


async def active(set_id: int, chat_id: int) -> dict[str, Any] | None:
    """Return the live run of one set and channel, if any."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_publication_runs).where(
                rule_publication_runs.c.rule_set_id == set_id,
                rule_publication_runs.c.chat_id == chat_id,
                rule_publication_runs.c.status == "running",
            )
        )
    )
    return dict(row) if row else None
