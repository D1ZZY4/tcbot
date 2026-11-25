# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Draft rule item CRUD."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text

from tcbot.database.base import (
    rule_categories,
    rule_items,
    rule_set_versions,
)
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    run,
    run_transaction,
)
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_items(
    version_id: int, category_key: str | None = None
) -> list[dict[str, Any]]:
    """Return items in display order, optionally limited to one category."""
    stmt = select(rule_items).where(rule_items.c.rule_set_version_id == version_id)
    if category_key is not None:
        stmt = stmt.where(rule_items.c.category_key == category_key)
    stmt = stmt.order_by(
        rule_items.c.category_sort_order,
        rule_items.c.category_key,
        rule_items.c.sort_order,
        rule_items.c.id,
    )
    rows = await db_call(lambda: fetch_all(stmt))
    return [dict(row) for row in rows]


async def _set_id(version_id: int) -> int:
    """Return the rule set a draft version belongs to.

    A published version is immutable: members already see its items and may
    have acknowledged it. Refusing the write here keeps a stale editor step
    from adding rules to it even if a caller skips the flow-level draft check.
    """
    row = await db_call(
        lambda: fetch_one(
            select(
                rule_set_versions.c.rule_set_id,
                rule_set_versions.c.status,
            ).where(rule_set_versions.c.id == version_id)
        )
    )
    if row is None:
        raise ValueError(f"Unknown rule version {version_id}")
    if row["status"] != "draft":
        raise ValueError(f"Rule version {version_id} is not a draft")
    return int(row["rule_set_id"])


async def _draft_set_id_in_tx(sess: AsyncSession, version_id: int) -> int:
    """Return the rule set of a draft version inside an active transaction."""
    row = (
        (
            await sess.execute(
                select(
                    rule_set_versions.c.rule_set_id,
                    rule_set_versions.c.status,
                ).where(rule_set_versions.c.id == version_id)
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError(f"Unknown rule version {version_id}")
    if row["status"] != "draft":
        raise ValueError(f"Rule version {version_id} is not a draft")
    return int(row["rule_set_id"])


def _rule_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "rule"


async def add_item(
    version_id: int,
    category_key: str,
    title: str,
    body: str,
    reference_url: str | None = None,
) -> dict[str, Any]:
    """Append an item to the draft with the current category snapshot."""

    async def _work(sess: AsyncSession) -> dict[str, Any]:
        # * Serialise item creation per draft so concurrent inserts cannot
        # * compute the same sort_order or collide on rule_key.
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"rules_items:{version_id}"},
        )
        set_id = await _draft_set_id_in_tx(sess, version_id)
        cat_row = (
            (
                await sess.execute(
                    select(rule_categories.c.title, rule_categories.c.sort_order).where(
                        rule_categories.c.rule_set_id == set_id,
                        rule_categories.c.category_key == category_key,
                    )
                )
            )
            .mappings()
            .first()
        )
        category_title = str(cat_row["title"]) if cat_row is not None else category_key
        category_order = int(cat_row["sort_order"]) if cat_row is not None else 100
        count = await sess.scalar(
            select(func.count())
            .select_from(rule_items)
            .where(rule_items.c.rule_set_version_id == version_id)
        )
        order = int(count or 0) + 1
        existing_keys = set(
            (
                await sess.scalars(
                    select(rule_items.c.rule_key).where(
                        rule_items.c.rule_set_version_id == version_id
                    )
                )
            ).all()
        )
        base_key = _rule_key(title)
        key = base_key
        suffix = 2
        while key in existing_keys:
            key = f"{base_key}-{suffix}"
            suffix += 1
        created = (
            (
                await sess.execute(
                    rule_items.insert()
                    .values(
                        rule_set_version_id=version_id,
                        rule_key=key,
                        category_key=category_key,
                        category_title=category_title,
                        category_sort_order=category_order,
                        title=title,
                        body=body,
                        content_format="plain_text",
                        sort_order=order,
                        is_mandatory=True,
                        reference_url=reference_url,
                        created_at=utc_now(),
                    )
                    .returning(rule_items)
                )
            )
            .mappings()
            .first()
        )
        if created is None:
            raise RuntimeError("The rule item was not written")
        return dict(created)

    return await run_transaction(_work)


async def update_item_body(version_id: int, item_id: int, body: str) -> bool:
    """Replace the body of one item in a draft. Published versions are refused."""
    await _set_id(version_id)
    affected = await db_call(
        lambda: run(
            rule_items.update()
            .where(
                rule_items.c.id == item_id,
                rule_items.c.rule_set_version_id == version_id,
            )
            .values(body=body)
        )
    )
    return affected > 0


async def delete_draft_category_items(version_id: int, category_key: str) -> int:
    """Remove every item of one category from a draft before a reseed."""
    await _set_id(version_id)
    return await db_call(
        lambda: run(
            rule_items.delete().where(
                rule_items.c.rule_set_version_id == version_id,
                rule_items.c.category_key == category_key,
            )
        )
    )


async def update_item_title(version_id: int, item_id: int, title: str) -> bool:
    """Replace the title of one item in a draft. Published versions are refused."""
    await _set_id(version_id)
    affected = await db_call(
        lambda: run(
            rule_items.update()
            .where(
                rule_items.c.id == item_id,
                rule_items.c.rule_set_version_id == version_id,
            )
            .values(title=title)
        )
    )
    return affected > 0
