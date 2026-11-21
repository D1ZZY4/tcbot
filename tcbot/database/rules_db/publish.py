# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Database transition that publishes a rules draft."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot.database.base import rule_set_versions
from tcbot.database.engine import run_transaction
from tcbot.database.rules_db.sets import WORKING_LOCALE
from tcbot.utils.time_and_date import utc_now


async def promote_version(version_id: int, user_id: int) -> None:
    """Supersede the old published version and publish this draft.

    The channel sync is deliberately outside this transaction: the database
    is the source of truth and a later publish reconciles a failed channel
    operation. Keeping the orchestration in the pipeline also keeps the
    storage layer free of Telegram imports.
    """

    async def _work(sess: AsyncSession) -> None:
        result = await sess.execute(
            select(rule_set_versions).where(rule_set_versions.c.id == version_id)
        )
        row = result.mappings().first()
        if row is None or row["status"] != "draft":
            raise RuntimeError("The rules draft no longer exists")
        set_id = int(row["rule_set_id"])
        await sess.execute(
            rule_set_versions.update()
            .where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
                rule_set_versions.c.status == "published",
            )
            .values(status="superseded", updated_at=utc_now())
        )
        await sess.execute(
            rule_set_versions.update()
            .where(rule_set_versions.c.id == version_id)
            .values(
                status="published",
                published_by_user_id=user_id,
                published_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    await run_transaction(_work)
