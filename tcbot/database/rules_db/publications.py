# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Channel message slots of a published rules version."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import rule_publications
from tcbot.database.engine import db_call, fetch_all, run
from tcbot.utils.time_and_date import utc_now


async def upsert_slot(
    *,
    set_id: int,
    version_id: int,
    locale: str,
    chat_id: int,
    message_thread_id: int | None,
    category_key: str,
    part_index: int,
    content_hash: str,
    run_id: int,
) -> dict[str, Any]:
    """Create or refresh one pending slot, keeping an existing message id."""
    values = {
        "rule_set_id": set_id,
        "rule_set_version_id": version_id,
        "locale": locale,
        "chat_id": chat_id,
        "message_thread_id": message_thread_id,
        "category_key": category_key,
        "part_index": part_index,
        "content_hash": content_hash,
        "run_id": run_id,
        "status": "pending",
        "updated_at": utc_now(),
    }
    rows = await db_call(
        lambda: fetch_all(
            pg_insert(rule_publications)
            .values(values)
            # * The schema creates a plain UNIQUE INDEX, not a named
            # * constraint, so ON CONFLICT ON CONSTRAINT would be refused by
            # * PostgreSQL. Target the indexed expression list instead; the
            # * nullable thread id must be coalesced exactly as in the index.
            .on_conflict_do_update(
                index_elements=[
                    rule_publications.c.rule_set_id,
                    rule_publications.c.locale,
                    rule_publications.c.chat_id,
                    func.coalesce(rule_publications.c.message_thread_id, 0),
                    rule_publications.c.category_key,
                    rule_publications.c.part_index,
                ],
                set_={
                    "rule_set_version_id": version_id,
                    "content_hash": content_hash,
                    "run_id": run_id,
                    "status": "pending",
                    "updated_at": utc_now(),
                },
            )
            .returning(rule_publications)
        )
    )
    return dict(rows[0])


async def mark_synced(slot_id: int, message_id: int) -> None:
    """Record that a channel message now matches the slot content."""
    await db_call(
        lambda: run(
            rule_publications.update()
            .where(rule_publications.c.id == slot_id)
            .values(
                message_id=message_id,
                status="synced",
                last_error=None,
                last_synced_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    )


async def mark_failed(slot_id: int, error: str, *, missing: bool = False) -> None:
    """Record a failed or missing channel message for the next publish.

    A missing message must drop its stale id: the publisher edits only when a
    message id exists, so keeping a deleted id would retry the dead message
    forever instead of sending a fresh one.
    """
    values: dict[str, Any] = {
        "status": "missing" if missing else "failed",
        "last_error": error[:500],
        "updated_at": utc_now(),
    }
    if missing:
        values["message_id"] = None
    await db_call(
        lambda: run(
            rule_publications.update()
            .where(rule_publications.c.id == slot_id)
            .values(**values)
        )
    )


async def retire_unused(set_id: int, keep_ids: list[int]) -> int:
    """Retire slots no longer part of the rendered channel representation.

    Slots are keyed by category and part, not by version: upserting a new
    version rewrites ``rule_set_version_id`` on reused slots, so filtering by
    the new version would match only the kept slots and retire nothing.
    Scope by set instead so dropped categories and shortened parts retire.
    """
    stmt = rule_publications.update().where(
        rule_publications.c.rule_set_id == set_id,
        rule_publications.c.status != "retired",
    )
    if keep_ids:
        stmt = stmt.where(rule_publications.c.id.not_in(keep_ids))
    return await db_call(
        lambda: run(stmt.values(status="retired", updated_at=utc_now()))
    )


async def status_counts(set_id: int) -> dict[str, int]:
    """Return the count of slots in each status for the editor panel."""
    rows = await db_call(
        lambda: fetch_all(
            select(rule_publications.c.status, func.count().label("count"))
            .where(rule_publications.c.rule_set_id == set_id)
            .group_by(rule_publications.c.status)
        )
    )
    return {str(row["status"]): int(row["count"]) for row in rows}
