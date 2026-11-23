# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Opening, cloning, and discarding rule drafts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot.database.base import (
    rule_categories,
    rule_items,
    rule_set_versions,
)
from tcbot.database.engine import db_call, fetch_all, fetch_one, run, run_transaction
from tcbot.database.rules_db.sets import WORKING_LOCALE
from tcbot.utils.time_and_date import utc_now


async def open_draft(
    set_id: int, user_id: int, *, clone_items: bool = True
) -> dict[str, Any]:
    """Return the open draft, cloning the published version when needed.

    A clone takes the current category catalogue as its snapshot, so a later
    rename or reorder cannot change the presentation of an older version.
    Callers that immediately replace the draft contents can skip the clone
    with ``clone_items=False``.
    """
    existing = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
                rule_set_versions.c.status == "draft",
            )
        )
    )
    if existing is not None:
        return dict(existing)

    published = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
                rule_set_versions.c.status == "published",
            )
        )
    )
    number_row = await db_call(
        lambda: fetch_one(
            select(
                func.coalesce(func.max(rule_set_versions.c.version_number), 0).label(
                    "max_version"
                )
            ).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
            )
        )
    )
    next_number = int(number_row["max_version"] if number_row else 0) + 1

    async def _work(sess: AsyncSession) -> int:
        created = await sess.execute(
            rule_set_versions.insert()
            .values(
                rule_set_id=set_id,
                version_number=next_number,
                locale=WORKING_LOCALE,
                status="draft",
                created_by_user_id=user_id,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            .returning(rule_set_versions.c.id)
        )
        version_id = int(created.scalar_one())
        if published is None or not clone_items:
            return version_id
        categories = (
            (
                await sess.execute(
                    select(rule_categories).where(
                        rule_categories.c.rule_set_id == set_id
                    )
                )
            )
            .mappings()
            .all()
        )
        snapshots = {
            str(row["category_key"]): (
                str(row["title"]),
                int(row["sort_order"]),
            )
            for row in categories
        }
        old_items = (
            (
                await sess.execute(
                    select(rule_items).where(
                        rule_items.c.rule_set_version_id == published["id"]
                    )
                )
            )
            .mappings()
            .all()
        )
        copied_at = utc_now()
        rows = []
        for item in old_items:
            title, order = snapshots.get(
                str(item["category_key"]), (str(item["category_key"]), 100)
            )
            rows.append(
                {
                    "rule_set_version_id": version_id,
                    "rule_key": item["rule_key"],
                    "category_key": item["category_key"],
                    "category_title": title,
                    "category_sort_order": order,
                    "title": item["title"],
                    "body": item["body"],
                    "content_format": item["content_format"],
                    "sort_order": item["sort_order"],
                    "is_mandatory": item["is_mandatory"],
                    "reference_url": item["reference_url"],
                    "metadata": item["metadata"],
                    "created_at": copied_at,
                }
            )
        # * One executemany round trip: the old per-row loop spent the whole
        # * database call budget on a published version with hundreds of items.
        if rows:
            await sess.execute(rule_items.insert(), rows)
        return version_id

    version_id = await run_transaction(_work)
    return {
        "id": version_id,
        "rule_set_id": set_id,
        "version_number": next_number,
        "locale": WORKING_LOCALE,
        "status": "draft",
    }


async def clear_draft_items(version_id: int) -> int:
    """Remove every item from a draft before it is filled by a reseed."""
    return await db_call(
        lambda: run(
            rule_items.delete().where(rule_items.c.rule_set_version_id == version_id)
        )
    )


async def discard_draft(version_id: int) -> bool:
    """Delete a draft version; published versions cannot be removed."""
    affected = await db_call(
        lambda: run(
            rule_set_versions.delete().where(
                rule_set_versions.c.id == version_id,
                rule_set_versions.c.status == "draft",
            )
        )
    )
    return affected > 0


async def published_version(set_id: int) -> dict[str, Any] | None:
    """Return the current published version of a set, if any."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
                rule_set_versions.c.status == "published",
            )
        )
    )
    return dict(row) if row is not None else None


async def all_items(version_id: int) -> list[dict[str, Any]]:
    """Return every item of one version."""
    rows = await db_call(
        lambda: fetch_all(
            select(rule_items).where(rule_items.c.rule_set_version_id == version_id)
        )
    )
    return [dict(row) for row in rows]
