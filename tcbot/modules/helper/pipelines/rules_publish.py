# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Publish a rules draft and sync it to the main channel."""

from __future__ import annotations

from typing import Any

from tcbot import cfg
from tcbot.database import rules_db
from tcbot.modules.helper.messages import safe_edit_message, send_text
from tcbot.modules.helper.messages.rules import content_hash, render_channel
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_dt_raw, utc_now

log = get_logger(__name__)


async def publish_rules(
    set_id: int, version_id: int, user_id: int, bot: Any
) -> dict[str, Any]:
    """Publish a draft and immediately reconcile the channel.

    The database commits before Telegram is touched. A failed channel
    operation is recorded on its slot and reconciled by the next publish;
    there is no separate sync command or background retry.
    """
    if cfg.main_channel == 0:
        raise RuntimeError("MAIN_CHANNEL is not configured; publishing is disabled")
    await rules_db.runs.reclaim_expired()
    run_id = await rules_db.runs.acquire(set_id, version_id, cfg.main_channel)
    try:
        items = await rules_db.all_items(version_id)
        if not items:
            raise RuntimeError("A rules draft needs at least one item before publish")
        previous = await rules_db.published_version(set_id)
        version_number = int(previous["version_number"]) + 1 if previous else 1
        parts = render_channel(
            items,
            version_number=version_number,
            published_at=fmt_dt_raw(utc_now()),
        )
        await rules_db.promote_version(version_id, user_id)

        synced = 0
        failed: list[str] = []
        keep_ids: list[int] = []
        for category, index, text in parts:
            digest = content_hash(text)
            slot = await rules_db.publications.upsert_slot(
                set_id=set_id,
                version_id=version_id,
                locale="en-US",
                chat_id=cfg.main_channel,
                message_thread_id=None,
                category_key=category,
                part_index=index,
                content_hash=digest,
                run_id=run_id,
            )
            keep_ids.append(int(slot["id"]))
            try:
                if slot.get("message_id") and slot.get("content_hash") == digest:
                    await safe_edit_message(
                        bot, cfg.main_channel, slot["message_id"], text
                    )
                    message_id = int(slot["message_id"])
                else:
                    sent = await send_text(bot, cfg.main_channel, text)
                    message_id = int(sent.message_id)
                await rules_db.publications.mark_synced(int(slot["id"]), message_id)
                synced += 1
            except Exception as exc:
                failed.append(f"{category} ({index + 1}): {exc}")
                await rules_db.publications.mark_failed(
                    int(slot["id"]), str(exc), missing="not found" in str(exc).lower()
                )
        await rules_db.publications.retire_unused(set_id, version_id, keep_ids)
        status = "completed" if not failed else "partial"
        await rules_db.runs.finish(run_id, status)
        return {"synced": synced, "failed": failed, "status": status}
    except Exception as exc:
        await rules_db.runs.finish(run_id, "failed", error=str(exc))
        raise
