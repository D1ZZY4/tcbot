# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB index setup: legacy reconciliation and parallel index creation."""

from __future__ import annotations

import asyncio

from tcbot.utils.logger import get_logger

from .client import _MEMBER_CACHE_EXPIRE_S, col, db_call

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mongos")

# * Auto-name shared by the retired plain until_date index and the current
# * TTL one (MongoDB names both "until_date_1").
_LEGACY_UNTIL_DATE_INDEX: str = "until_date_1"


async def _drop_legacy_active_mutes_index() -> None:
    """Drop a pre-TTL ``until_date_1`` index left by older releases.

    Releases before the TTL migration created a plain ``(until_date)``
    index under the same auto-name the TTL variant needs, so creating it
    fails with ``IndexOptionsConflict`` (code 85) and the fail-fast
    startup aborts before serving traffic. Databases already on the TTL
    variant (or fresh ones) skip this: the drop runs only when the
    existing index lacks ``expireAfterSeconds``. Startup has not served
    traffic yet, so the brief window without the single-field index is
    safe: the ``(user_id, until_date)`` compound still serves per-user
    reads, and the TTL recreate lands immediately after.
    """
    try:
        existing = await db_call(col("active_mutes").list_indexes().to_list(None))
    except Exception as exc:
        log.debug("active_mutes index reconciliation skipped: %s", exc)
        return
    for spec in existing:
        if spec.get("name") != _LEGACY_UNTIL_DATE_INDEX:
            continue
        if "expireAfterSeconds" in spec:
            return
        try:
            await db_call(col("active_mutes").drop_index(_LEGACY_UNTIL_DATE_INDEX))
        except Exception as exc:
            log.warning("Dropping legacy active_mutes index failed: %s", exc)
            return
        log.info("Dropped legacy non-TTL active_mutes.until_date_1 index.")
        return


async def ensure_indexes() -> None:
    """Create all critical collection indexes in parallel. No-op if they already exist.

    Raises the first index failure after logging every failure, so the
    fail-fast checks in ``__main__._post_init`` and ``serverless`` startup
    actually fire. Serving traffic without uniqueness indexes (bans
    ``ban_id``, ``warn_counts`` per-user counter, one-pending-request) risks
    duplicate moderation records, which is worse than a loud startup crash
    that the runner watchdog restarts from.
    """
    # * Sequential pre-step, not part of the gather below: a legacy plain
    # * until_date_1 index must be gone before the TTL recreate runs, or
    # * the recreate conflicts and this same fail-fast fires.
    await _drop_legacy_active_mutes_index()
    results = await asyncio.gather(
        # * Serves get_active_ban(): filter on banned_user_id + is_active, sort on
        # * timestamp + ban_id. Compound index replaces the separate prefix index below.
        col("bans").create_index(
            [("banned_user_id", 1), ("is_active", 1), ("timestamp", -1), ("ban_id", -1)]
        ),
        col("bans").create_index([("ban_id", 1)], unique=True),
        col("tc_owners").create_index([("user_id", 1)], unique=True),
        # * Serves user_appeal_count() which filters on banned_user_id + appeal_log_msg_id presence
        col("bans").create_index(
            [("banned_user_id", 1), ("appeal_log_msg_id", 1)], sparse=True
        ),
        # * Covering index for active_ban_user_ids() DISTINCT over the
        # * active slice: answers from the index without fetching documents.
        col("bans").create_index([("is_active", 1), ("banned_user_id", 1)]),
        # * Serves mtproto_store peer lookups by username / phone number.
        col("mtproto_state").create_index([("usernames", 1)], sparse=True),
        col("mtproto_state").create_index([("phone_number", 1)], sparse=True),
        # * Serves active_ban_count()/active_bans_page() which filter on is_active only
        col("bans").create_index([("is_active", 1), ("timestamp", -1), ("ban_id", -1)]),
        # * Serves /check history: every ban (active+inactive) for a user, newest first
        col("bans").create_index(
            [("banned_user_id", 1), ("timestamp", -1), ("ban_id", -1)]
        ),
        col("tc_admins").create_index([("user_id", 1)], unique=True),
        col("tc_roles").create_index([("user_id", 1)], unique=True),
        # * Serves users_roles.all_by_role() which filters by role only
        col("tc_roles").create_index([("role", 1)]),
        col("federated_groups").create_index([("chat_id", 1), ("is_active", 1)]),
        col("federated_groups").create_index([("chat_id", 1)], unique=True),
        # * pending_joins keyed by chat_id with upsert (one pending per chat)
        col("pending_joins").create_index([("chat_id", 1)], unique=True),
        col("member_cache").create_index([("user_id", 1)], unique=True),
        # * Covered-query index: serves get_first_names_batch and get_mention_data_batch
        # * $in on user_id with {first_name,username,last_name} projection; all fields in index
        col("member_cache").create_index(
            [("user_id", 1), ("first_name", 1), ("username", 1), ("last_name", 1)]
        ),
        # * Serves batch username lookups and search operations
        col("member_cache").create_index([("username", 1)]),
        # * Serves user_settings lookups by user: one preference row per user.
        col("user_settings").create_index([("user_id", 1)], unique=True),
        # * Serves name search operations (case-insensitive search by first_name)
        col("member_cache").create_index([("first_name", 1)]),
        col("warns").create_index([("user_id", 1), ("chat_id", 1), ("timestamp", -1)]),
        # * Serves /check history: every warning for a user across groups
        col("warns").create_index([("user_id", 1), ("timestamp", -1)]),
        # * Serves get_warns() sorts in both directions (newest-first
        # * paged views and oldest-first full reads).
        col("warns").create_index([("user_id", 1), ("chat_id", 1), ("timestamp", 1)]),
        # * Serves warn expiry: delete_many({"timestamp": {"$lt": cutoff}}) COLLSCAN without this
        col("warns").create_index([("timestamp", 1)]),
        # * Serves migrate_records(): update_many on chat_id alone COLLSCANs
        # * the user_id-led indexes above on every group upgrade otherwise.
        col("warns").create_index([("chat_id", 1)]),
        col("warn_counts").create_index([("user_id", 1), ("chat_id", 1)], unique=True),
        # * Serves warn expiry: delete_many({"updated_at": {"$lt": cutoff}}) COLLSCAN without this
        col("warn_counts").create_index([("updated_at", 1)]),
        # * Serves user_warn_groups() and federation_warn_count() filter + sort
        col("warn_counts").create_index(
            [("user_id", 1), ("count", 1), ("updated_at", -1)]
        ),
        # * Serves migrate_records() on warn_counts (see warns chat_id note).
        col("warn_counts").create_index([("chat_id", 1)]),
        # * Per-user kick / mute history for /check
        col("kicks").create_index([("user_id", 1), ("timestamp", -1)]),
        col("mutes").create_index([("user_id", 1), ("timestamp", -1)]),
        col("promotion_requests").create_index([("request_id", 1)], unique=True),
        col("promotion_requests").create_index([("target_id", 1), ("status", 1)]),
        # * One pending request per user: concurrent promotes for the same
        # * target collapse into a single queue entry instead of duplicates.
        col("promotion_requests").create_index(
            [("target_id", 1)],
            unique=True,
            partialFilterExpression={"status": "pending"},
        ),
        # * Serves queues_db.all_pending() which filters on status and sorts
        # * by requested_date; compound avoids an in-memory sort.
        col("promotion_requests").create_index([("status", 1), ("requested_date", 1)]),
        col("kicks").create_index([("chat_id", 1)]),
        col("mutes").create_index([("chat_id", 1)]),
        col("federated_groups").create_index([("is_active", 1)]),
        # * active_mutes: one document per muted user (upserted by set_active_mute)
        col("active_mutes").create_index([("user_id", 1)], unique=True),
        # * Compound for get_active_mute() $or filter on specific user
        col("active_mutes").create_index([("user_id", 1), ("until_date", 1)]),
        # * TTL doubles as the expiry-filtered fetch index for
        # * active_mute_docs()/get_active_mute(): same key as the retired
        # * plain index, so no separate single-field index is kept.
        # * MongoDB auto-names both "until_date_1" and refuses the duplicate
        # * with IndexOptionsConflict, hence the pre-step drop above.
        # * MongoDB auto-deletes expired timed mutes (until_date <= now).
        # * Permanent mutes (until_date None/missing) are never TTL-expired,
        # * matching the query-time filter in get_active_mute/active_mute_docs,
        # * so this only prunes rows those queries already ignore.
        col("active_mutes").create_index([("until_date", 1)], expireAfterSeconds=0),
        # * TTL index: MongoDB auto-expires member_cache docs older than _MEMBER_CACHE_TTL_DAYS.
        # * Replaces the APScheduler weekly cleanup job, shrinking the scheduler surface.
        col("member_cache").create_index(
            [("last_updated", 1)], expireAfterSeconds=_MEMBER_CACHE_EXPIRE_S
        ),
        return_exceptions=True,
    )
    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        for exc in failed:
            log.error("Index creation failed: %s", exc)
        # * Re-raise (preserving cancellation) instead of limping on without
        # * indexes: the startup fail-fast checks depend on this raising.
        raise failed[0]
    log.info(
        "MongoDB indexes ensured (%d/%d succeeded).",
        len(results) - len(failed),
        len(results),
    )
