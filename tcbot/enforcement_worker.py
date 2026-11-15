# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Deliver the queued expiry revokes to Telegram.

The database expires a decision and queues one revoke run per managed
group. This worker claims those runs and lifts the restriction, so the
queue is not a write-only ledger. The work is idempotent: an expired
action can be unbanned or unrestricted more than once without harm.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from telegram import ChatPermissions

from tcbot import database as db
from tcbot.utils.dispatch import (
    fan_out,
    gather_bounded,
    is_benign_telegram_error,
    throw_if_cancelled,
)
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

_BOT: Bot | None = None
_MAX_RUNS_PER_TICK: int = 10
_MAX_TARGETS_PER_RUN: int = 100
_MAX_ATTEMPTS: int = 3
_RETRY_DELAY = timedelta(minutes=5)


def _as_int(value: object) -> int:
    """Read a database integer column without trusting its runtime type."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def configure(bot: Bot) -> None:
    """Attach the live bot the scheduled job must use."""
    global _BOT
    _BOT = bot


async def run() -> None:
    """APScheduler entry point: drain the queue once."""
    if _BOT is None:
        log.debug("Enforcement worker skipped: no bot is attached.")
        return
    try:
        await run_once(_BOT)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Enforcement worker tick failed.")


async def run_once(bot: Bot) -> None:
    """Claim and process the queued enforcement runs.

    A run that fails is logged and left for the stale-run requeue; the
    remaining claimed runs still execute, so one bad decision cannot
    starve every other expiry in the same tick.
    """
    await db.enforcement_db.requeue_stale_runs()
    runs = await db.enforcement_db.claim_runs(_MAX_RUNS_PER_TICK)
    for run in runs:
        try:
            await _process_run(bot, run)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Enforcement run %s failed; continuing with the next run.",
                run.get("id"),
            )


async def _process_run(bot: Bot, run: dict[str, object]) -> None:
    """Process one claimed run, one target at a time within the run."""
    run_id = _as_int(run.get("id"))
    if run_id <= 0:
        return
    action = await db.enforcement_db.load_run_action(run_id)
    if action is None or action.get("action_status") not in ("expired", "revoked"):
        await db.enforcement_db.cancel_run(
            run_id, error_detail="the action is no longer expired or revoked"
        )
        return
    action_type = str(action.get("action_type") or "")
    target_user_id = _as_int(action.get("target_user_id"))
    if action_type not in ("ban", "mute") or target_user_id <= 0:
        await db.enforcement_db.cancel_run(
            run_id, error_detail=f"unsupported action type {action_type!r}"
        )
        return

    targets = await db.enforcement_db.claim_targets(run_id, _MAX_TARGETS_PER_RUN)
    if not targets:
        await db.enforcement_db.complete_empty_run(run_id)
        return

    coros = [
        _deliver(bot, action_type, _as_int(target.get("chat_id")), target_user_id)
        for target in targets
    ]
    results = await fan_out(coros)
    throw_if_cancelled(results)

    updates = [
        _record_target(target, result)
        for target, result in zip(targets, results, strict=False)
    ]
    settled = await gather_bounded(updates, max_concurrent=10)
    for result in settled:
        if isinstance(result, BaseException):
            log.error("Enforcement target update failed: %s", result)


async def _deliver(bot: Bot, action_type: str, chat_id: int, user_id: int) -> None:
    """Lift one expired restriction in one chat."""
    if chat_id == 0:
        return
    async with asyncio.timeout(20):
        if action_type == "ban":
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        else:
            await bot.restrict_chat_member(
                chat_id, user_id, permissions=ChatPermissions.all_permissions()
            )


async def _record_target(target: dict[str, object], result: object) -> None:
    """Persist one target result and schedule a bounded retry on failure."""
    target_id = _as_int(target.get("id"))
    attempts = _as_int(target.get("attempt_count"))
    if target_id <= 0:
        return
    if result is None:
        await db.enforcement_db.complete_target(
            target_id, status="succeeded", outcome="succeeded"
        )
        return
    if isinstance(result, BaseException) and is_benign_telegram_error(result):
        await db.enforcement_db.complete_target(
            target_id,
            status="skipped",
            outcome="skipped",
            error_kind=type(result).__name__,
            error_detail=str(result),
        )
        return
    detail = str(result)
    retry = attempts < _MAX_ATTEMPTS
    # * The target trigger only accepts in_progress -> succeeded|skipped|failed.
    # * A retry is a failed attempt with a due deadline, not a return to
    # * pending; writing pending here aborts the attempt insert and strands
    # * the target in_progress, which keeps its run running forever.
    await db.enforcement_db.complete_target(
        target_id,
        status="failed",
        outcome="failed",
        error_kind=type(result).__name__ if isinstance(result, BaseException) else None,
        error_detail=detail,
        retry_after=_RETRY_DELAY if retry else None,
    )
