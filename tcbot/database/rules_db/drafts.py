# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Opening, cloning, and discarding rule drafts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
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
    set_id: int,
    user_id: int,
    *,
    clone_items: bool = True,
    locale: str | None = None,
) -> dict[str, Any]:
    """Return the open draft, cloning the published version when needed.

    A clone takes the current category catalogue as its snapshot, so a later
    rename or reorder cannot change the presentation of an older version.
    Callers that immediately replace the draft contents can skip the clone
    with ``clone_items=False``. The content locale selects the draft to open.
    """
    content_locale = locale or WORKING_LOCALE

    async def _work(sess: AsyncSession) -> dict[str, Any]:
        # * Serialise draft creation per (set_id, locale) so concurrent
        # * callers reuse the same draft instead of racing on the unique index.
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"rules_draft:{set_id}:{content_locale}"},
        )
        existing = (
            (
                await sess.execute(
                    select(rule_set_versions).where(
                        rule_set_versions.c.rule_set_id == set_id,
                        rule_set_versions.c.locale == content_locale,
                        rule_set_versions.c.status == "draft",
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return dict(existing)

        published = (
            (
                await sess.execute(
                    select(rule_set_versions).where(
                        rule_set_versions.c.rule_set_id == set_id,
                        rule_set_versions.c.locale == content_locale,
                        rule_set_versions.c.status == "published",
                    )
                )
            )
            .mappings()
            .first()
        )
        max_version = await sess.scalar(
            select(
                func.coalesce(func.max(rule_set_versions.c.version_number), 0)
            ).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == content_locale,
            )
        )
        next_number = int(max_version or 0) + 1
        now = utc_now()
        created = (
            (
                await sess.execute(
                    rule_set_versions.insert()
                    .values(
                        rule_set_id=set_id,
                        version_number=next_number,
                        locale=content_locale,
                        status="draft",
                        created_by_user_id=user_id,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(rule_set_versions)
                )
            )
            .mappings()
            .first()
        )
        if created is None:
            raise RuntimeError("The rules draft was not written")
        draft_doc = dict(created)
        version_id = int(draft_doc["id"])
        if published is None or not clone_items:
            return draft_doc
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
        return draft_doc

    return await run_transaction(_work)


async def clear_draft_items(version_id: int) -> int:
    """Remove every item from a draft before it is filled by a reseed."""
    return await db_call(
        lambda: run(
            rule_items.delete().where(rule_items.c.rule_set_version_id == version_id)
        )
    )


async def discard_draft(version_id: int) -> bool:
    """Delete a draft version and its items in one atomic unit.

    The version cannot be removed while its items reference it, so both
    deletes must share a transaction. A published version is never touched.
    """

    async def _work(sess: AsyncSession) -> int:
        row = await sess.execute(
            select(rule_set_versions.c.id).where(
                rule_set_versions.c.id == version_id,
                rule_set_versions.c.status == "draft",
            )
        )
        if row.first() is None:
            return 0
        await sess.execute(
            rule_items.delete().where(rule_items.c.rule_set_version_id == version_id)
        )
        await sess.execute(
            rule_set_versions.delete().where(rule_set_versions.c.id == version_id)
        )
        return 1

    return await run_transaction(_work) > 0


async def published_version(
    set_id: int, locale: str | None = None
) -> dict[str, Any] | None:
    """Return the current published version of a set, if any."""
    content_locale = locale or WORKING_LOCALE
    row = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == content_locale,
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
