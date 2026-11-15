# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Deliver the queued enforcement runs to Telegram.

The database records a decision and queues one run per managed group.
This worker applies or lifts the decision for each target, records the
per-group outcome, and retries a transient failure. The work is
idempotent: a ban, mute, unban, or restore can be delivered more than
once without harm.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
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


async def deliver_queued_run(bot: Bot, run_id: int) -> bool:
    """Deliver one queued run now; return False when another worker owns it.

    The caller has already committed the decision and its run, so failing
    to claim it is not an error: the scheduled worker delivers it, and the
    run stays recoverable if this process dies before the claim.
    """
    run = await db.enforcement_db.claim_run(run_id)
    if run is None:
        return False
    await _process_run(bot, run)
    return True


async def _process_run(bot: Bot, run: dict[str, object]) -> None:
    """Process one claimed run, one target at a time within the run."""
    run_id = _as_int(run.get("id"))
    if run_id <= 0:
        return
    action = await db.enforcement_db.load_run_action(run_id)
    if action is None:
        await db.enforcement_db.cancel_run(
            run_id, error_detail="the action of the run no longer exists"
        )
        return
    operation = str(action.get("operation") or "")
    action_status = str(action.get("action_status") or "")
    action_type = str(action.get("action_type") or "")
    supported = (
        (
            operation == "apply"
            and action_status == "active"
            and action_type in ("ban", "mute")
        )
        or (
            operation == "revoke"
            and action_status in ("expired", "revoked")
            and action_type in ("ban", "mute")
        )
        or (
            operation == "reconcile"
            and action_status == "completed"
            and action_type == "kick"
        )
    )
    if not supported:
        await db.enforcement_db.cancel_run(
            run_id,
            error_detail=(
                f"unsupported {operation!r} run for "
                f"{action_type!r} action in {action_status!r} state"
            ),
        )
        return
    target_user_id = _as_int(action.get("target_user_id"))
    if target_user_id <= 0:
        await db.enforcement_db.cancel_run(
            run_id, error_detail="the action carries no target"
        )
        return

    targets = await db.enforcement_db.claim_targets(run_id, _MAX_TARGETS_PER_RUN)
    if not targets:
        await db.enforcement_db.complete_empty_run(run_id)
        return

    expires_at = action.get("expires_at")
    expiry = expires_at if isinstance(expires_at, datetime) else None
    coros = [
        _deliver(
            bot,
            action_type,
            _as_int(target.get("chat_id")),
            target_user_id,
            operation,
            expiry,
        )
        for target in targets
    ]
    results = await fan_out(coros)
    throw_if_cancelled(results)

    updates = [
        _record_target(target, result)
        for target, result in zip(targets, results, strict=True)
    ]
    settled = await gather_bounded(updates, max_concurrent=10)
    for result in settled:
        if isinstance(result, BaseException):
            log.error("Enforcement target update failed: %s", result)


async def _deliver(
    bot: Bot,
    action_type: str,
    chat_id: int,
    user_id: int,
    operation: str,
    expires_at: datetime | None = None,
) -> None:
    """Apply or lift one decision in one chat."""
    if chat_id == 0:
        return
    async with asyncio.timeout(20):
        if operation == "apply":
            if action_type == "ban":
                await bot.ban_chat_member(chat_id, user_id)
            else:
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=expires_at,
                )
            return
        if action_type in ("ban", "kick"):
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
