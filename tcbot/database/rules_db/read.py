# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Read surfaces for published rules and acknowledgements."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import (
    rule_acknowledgements,
    rule_categories,
    rule_category_content,
    rule_items,
    rule_set_versions,
    rule_sets,
)
from tcbot.database.engine import db_call, fetch_all, fetch_one, run_returning
from tcbot.database.rules_db.sets import WORKING_LOCALE
from tcbot.utils.time_and_date import utc_now


async def _category_presentation(
    set_id: int, locale: str | None
) -> dict[str, dict[str, str]]:
    """Return the database-owned labels and descriptions for a reader locale.

    Nothing is generated or defaulted from bundled text: a category without a
    stored row simply has no presentation, and the caller falls back to its
    stored title.
    """
    rows = await db_call(
        lambda: fetch_all(
            rule_category_content.select().where(
                rule_category_content.c.rule_set_id == set_id
            )
        )
    )
    wanted = locale or WORKING_LOCALE
    by_key: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        key = str(row["category_key"])
        by_key.setdefault(key, {})[str(row["locale"])] = {
            "label": str(row["label"]),
            "description": str(row["description"] or ""),
        }
    result: dict[str, dict[str, str]] = {}
    for key, localized in by_key.items():
        default = localized.get(WORKING_LOCALE, {})
        chosen = localized.get(wanted, default)
        result[key] = {
            "label": chosen.get("label") or default.get("label") or "",
            "description": (
                chosen.get("description") or default.get("description") or ""
            ),
        }
    return result


async def published_rules(
    set_id: int | None = None, locale: str | None = None
) -> dict[str, Any] | None:
    """Return the active published version with its items and categories.

    Category presentation is resolved for *locale* from the database, so the
    public menu follows the reader's language without a translation catalog.
    """
    if set_id is None:
        set_row = await db_call(
            lambda: fetch_one(
                select(rule_sets.c.id).where(
                    rule_sets.c.scope_type == "community",
                    rule_sets.c.is_active.is_(True),
                )
            )
        )
        if set_row is None:
            return None
        set_id = int(set_row["id"])
    content_locale = locale or WORKING_LOCALE
    version = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == content_locale,
                rule_set_versions.c.status == "published",
            )
        )
    )
    if version is None and content_locale != WORKING_LOCALE:
        version = await db_call(
            lambda: fetch_one(
                select(rule_set_versions).where(
                    rule_set_versions.c.rule_set_id == set_id,
                    rule_set_versions.c.locale == WORKING_LOCALE,
                    rule_set_versions.c.status == "published",
                )
            )
        )
    if version is None:
        return None
    # * These reads depend only on set_id, locale, and the now-known version
    # * id. They are independent pure reads, so one gather avoids four serial
    # * pool checkouts on every rules-menu tap.
    items, categories, set_doc, content = await asyncio.gather(
        db_call(
            lambda: fetch_all(
                select(rule_items)
                .where(rule_items.c.rule_set_version_id == version["id"])
                .order_by(rule_items.c.sort_order, rule_items.c.id)
            )
        ),
        db_call(
            lambda: fetch_all(
                select(rule_categories)
                .where(rule_categories.c.rule_set_id == set_id)
                .order_by(rule_categories.c.sort_order, rule_categories.c.id)
            )
        ),
        db_call(lambda: fetch_one(select(rule_sets).where(rule_sets.c.id == set_id))),
        _category_presentation(set_id, locale),
    )
    titles = {str(row["category_key"]): str(row["title"]) for row in categories}
    resolved_categories: list[dict[str, Any]] = []
    for row in categories:
        category = dict(row)
        key = str(category["category_key"])
        presentation = content.get(key)
        category["label"] = (
            presentation["label"] if presentation else ""
        ) or titles.get(key, key)
        # * The editor owns the category description; the localized content
        # * table is the fallback when no description was written in bot.
        stored = str(category.get("description") or "")
        category["description"] = stored or (
            presentation["description"] if presentation else ""
        )
        resolved_categories.append(category)
    return {
        "set": dict(set_doc) if set_doc else {},
        "version": dict(version),
        "items": [dict(row) for row in items],
        "categories": resolved_categories,
    }


async def acknowledgement_requirement(
    locale: str | None = None,
) -> tuple[int, bool] | None:
    """Return the published version id and acknowledgement flag for a reader.

    The version must be the one the reader actually sees in `/rules`: the
    reader locale first, then the working-locale fallback used by
    :func:`published_rules`. Button construction and tap validation both use
    this helper, so they cannot disagree about the authoritative version.
    """

    async def _read(content_locale: str) -> dict[str, Any] | None:
        return await db_call(
            lambda: fetch_one(
                select(
                    rule_set_versions.c.id.label("version_id"),
                    rule_sets.c.requires_acknowledgement,
                )
                .select_from(
                    rule_set_versions.join(
                        rule_sets, rule_set_versions.c.rule_set_id == rule_sets.c.id
                    )
                )
                .where(
                    rule_sets.c.scope_type == "community",
                    rule_sets.c.is_active.is_(True),
                    rule_set_versions.c.locale == content_locale,
                    rule_set_versions.c.status == "published",
                )
                .order_by(rule_set_versions.c.id.desc())
                .limit(1)
            )
        )

    content_locale = locale or WORKING_LOCALE
    row = await _read(content_locale)
    if row is None and content_locale != WORKING_LOCALE:
        row = await _read(WORKING_LOCALE)
    if row is None:
        return None
    return int(row["version_id"]), bool(row["requires_acknowledgement"])


async def acknowledgement_count(version_id: int) -> int:
    """Return how many users accepted one published version."""
    row = await db_call(
        lambda: fetch_one(
            select(func.count().label("count"))
            .select_from(rule_acknowledgements)
            .where(rule_acknowledgements.c.rule_set_version_id == version_id)
        )
    )
    return int(row["count"] if row else 0)


async def has_acknowledged(version_id: int, user_id: int) -> bool:
    """Return whether one user already accepted this exact version."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_acknowledgements.c.id).where(
                rule_acknowledgements.c.rule_set_version_id == version_id,
                rule_acknowledgements.c.user_id == user_id,
            )
        )
    )
    return row is not None


async def record_acknowledgement(
    version_id: int,
    user_id: int,
    context_chat_id: int | None,
    message_id: int | None,
) -> bool:
    """Insert one acknowledgement; duplicate taps are safe."""
    # * An acknowledgement is an insert, so it belongs on the write boundary
    # * even though the returned id is only used as a presence flag.
    result = await db_call(
        lambda: run_returning(
            pg_insert(rule_acknowledgements)
            .values(
                rule_set_version_id=version_id,
                user_id=user_id,
                context_chat_id=context_chat_id,
                acknowledgement_method="inline_button",
                telegram_message_id=message_id,
                acknowledged_at=utc_now(),
                metadata={"source": "greeting"},
            )
            .on_conflict_do_nothing(index_elements=["rule_set_version_id", "user_id"])
            .returning(rule_acknowledgements.c.id)
        )
    )
    return bool(result)
