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

from pyrogram import Client
from pyrogram.types import ChatPermissions

from tcbot import database as db
from tcbot.database.types import as_int
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.circuit_breaker import CircuitState
from tcbot.utils.dispatch import (
    fan_out,
    gather_bounded,
    is_benign_telegram_error,
    is_permanent_telegram_error,
    throw_if_cancelled,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import to_utc, utc_now
from tcbot.utils.transport import TELEGRAM_ACTION_TIMEOUT

log = get_logger(__name__)

_BOT: Client | None = None
_MAX_RUNS_PER_TICK: int = 10
_MAX_TARGETS_PER_RUN: int = 100
# * Upper bound on one delivery chunk; the breaker headroom tightens it further.
_DELIVERY_CHUNK: int = 10
_MAX_ATTEMPTS: int = db.enforcement_db.MAX_ATTEMPTS
_RETRY_DELAY = timedelta(minutes=5)


def configure(bot: Client) -> None:
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


async def run_once(bot: Client) -> None:
    """Claim and process the queued enforcement runs.

    A run that fails is logged and left for the stale-run requeue; the
    remaining claimed runs still execute, so one bad decision cannot
    starve every other expiry in the same tick.
    """
    await db.enforcement_db.requeue_stale_runs()
    # * Claiming a target consumes one of its three attempts even when the
    # * Telegram circuit is open and the call is skipped before it leaves the
    # * process. Leave the work queued while the circuit is OPEN so an outage
    # * cannot exhaust the retry budget without a single delivery attempt.
    # * Reading ``state`` (not ``peek_state``) lets an elapsed recovery window
    # * move the breaker to HALF_OPEN and admit its single probe.
    state = _cb.telegram.state
    if state is CircuitState.OPEN:
        log.warning(
            "Enforcement worker paused: Telegram circuit is OPEN; "
            "queued runs stay available for the next tick."
        )
        return
    # * HALF_OPEN admits one probe. Claiming a full batch would make fan_out
    # * skip every other slot and record each skip as a failed attempt that
    # * never reached Telegram, exhausting the retry budget across the whole
    # * federation during recovery. Deliver the probe; the other targets stay
    # * queued for the next tick once the probe closes the circuit.
    probe_only = state is CircuitState.HALF_OPEN
    # * Reserve before claiming: an immediate delivery and the scheduled tick
    # * can interleave at the database awaits. Without this reservation both
    # * would claim a target, and the loser would record a skipped slot as a
    # * failed attempt even though no Telegram call was made.
    if probe_only and not _cb.telegram.try_acquire():
        log.debug("Enforcement worker deferred: the recovery probe is in use.")
        return
    try:
        runs = await db.enforcement_db.claim_runs(
            1 if probe_only else _MAX_RUNS_PER_TICK
        )
        for run in runs:
            try:
                await _process_run(
                    bot,
                    run,
                    max_targets=1 if probe_only else _MAX_TARGETS_PER_RUN,
                    probe_reserved=probe_only,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "Enforcement run %s failed; continuing with the next run.",
                    run.get("id"),
                )
    finally:
        if probe_only:
            # * Idempotent when a delivery already settled the probe; releases
            # * it when the run was cancelled or never reached Telegram.
            _cb.telegram.release_probe()


async def deliver_queued_run(bot: Client, run_id: int) -> bool:
    """Deliver one queued run now; return False when another worker owns it.

    The caller has already committed the decision and its run, so failing
    to claim it is not an error: the scheduled worker delivers it, and the
    run stays recoverable if this process dies before the claim.

    An OPEN Telegram circuit skips the claim entirely. A slot skipped by
    the breaker never reaches Telegram, and recording it as a failed
    attempt would exhaust the target's retry budget without a delivery.
    The run stays queued for the scheduled worker, which pauses while the
    circuit is open.
    """
    state = _cb.telegram.state
    if state is CircuitState.OPEN:
        log.warning(
            "Enforcement run %s delivered later: Telegram circuit is OPEN.",
            run_id,
        )
        return False
    probe_reserved = state is CircuitState.HALF_OPEN
    # * The scheduled tick can hold the recovery probe at the same moment.
    # * Leaving the run queued is safe; claiming its target and recording a
    # * skipped slot as a failed attempt is not.
    if probe_reserved and not _cb.telegram.try_acquire():
        log.debug(
            "Enforcement run %s delivered later: the recovery probe is in use.",
            run_id,
        )
        return False
    try:
        run = await db.enforcement_db.claim_run(run_id)
        if run is None:
            return False
        await _process_run(
            bot,
            run,
            max_targets=1 if probe_reserved else _MAX_TARGETS_PER_RUN,
            probe_reserved=probe_reserved,
        )
        return True
    finally:
        if probe_reserved:
            _cb.telegram.release_probe()


async def _process_run(
    bot: Client,
    run: dict[str, object],
    *,
    max_targets: int = _MAX_TARGETS_PER_RUN,
    probe_reserved: bool = False,
) -> None:
    """Process one claimed run, up to *max_targets* targets at a time."""
    run_id = as_int(run.get("id"))
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
            and action_status in ("completed", "failed")
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
    if operation == "revoke" and bool(action.get("newer_active")):
        # * A later decision of the same type is in force. Lifting the
        # * restriction here would undo the newer ban or mute, which is
        # * exactly what a retried revoke after a re-ban must not do.
        await db.enforcement_db.cancel_run(
            run_id,
            error_detail=(
                "a newer active decision of the same type supersedes this revoke"
            ),
        )
        return
    if operation == "reconcile" and bool(action.get("active_ban")):
        # * A kick converts a ban into a rejoin, but a federation ban now
        # * holds the target. The repair unban would lift that ban.
        await db.enforcement_db.cancel_run(
            run_id,
            error_detail="an active federation ban supersedes the kick repair",
        )
        return
    expires_at = action.get("expires_at")
    expiry = expires_at if isinstance(expires_at, datetime) else None
    # * A timed decision that ran out while its run waited is no longer in
    # * force. Applying it would ban or mute a user after the deadline the
    # * moderator set; the revoke run cannot undo the time already served.
    if operation == "apply" and expiry is not None:
        remaining = to_utc(expiry) - utc_now()
        if remaining <= timedelta(0):
            await db.enforcement_db.cancel_run(
                run_id,
                error_detail="the decision expired before its delivery",
            )
            return
        # * Telegram treats a restriction shorter than 30 seconds as forever.
        # * Applying a nearly expired mute would leave the user restricted
        # * indefinitely while the database says it already ended.
        if action_type == "mute" and remaining < timedelta(seconds=30):
            await db.enforcement_db.cancel_run(
                run_id,
                error_detail="the mute would reach Telegram with under 30s left",
            )
            return
    target_user_id = as_int(action.get("target_user_id"))
    if target_user_id <= 0:
        await db.enforcement_db.cancel_run(
            run_id, error_detail="the action carries no target"
        )
        return
    # * A warn-threshold ban is deferred to this worker. The handler cannot
    # * clear warnings for chats that have not landed yet, so every chunk of
    # * this run clears its own landed chats. Manual bans never touch warns.
    warn_clear_user = 0
    if (
        operation == "apply"
        and action_status == "active"
        and action_type == "ban"
        and str(action.get("action_origin") or "") == "automated"
    ):
        warn_clear_user = target_user_id

    # * Claim in small chunks capped by the breaker's remaining failure
    # * headroom. A claim consumes one of the target's three attempts before
    # * the call starts, so claiming more than the circuit can admit would
    # * let a mid-batch OPEN leave later slots skipped without a delivery and
    # * exhaust their budget across a few outages.
    results: list[object] = []
    processed = 0
    update_failed = False
    while processed < max_targets:
        state = _cb.telegram.state
        if state is CircuitState.OPEN:
            break
        if state is CircuitState.HALF_OPEN:
            chunk_size = 1
        else:
            chunk_size = min(
                _DELIVERY_CHUNK,
                max_targets - processed,
                _cb.telegram.admission_headroom,
            )
            if chunk_size <= 0:
                break
        targets = await db.enforcement_db.claim_targets(run_id, chunk_size)
        if not targets:
            if not results:
                # * A repair with no claimable target is not a successful
                # * unban: the chat may be disconnected, so the record stays
                # * failed and visible.
                await db.enforcement_db.complete_empty_run(run_id)
            break
        coros = [
            _deliver(
                bot,
                action_type,
                as_int(target.get("chat_id")),
                target_user_id,
                operation,
                expiry,
            )
            for target in targets
        ]
        # * The caller reserved the recovery probe before claiming the run.
        # * Pass that fact down so the slot does not reject its own probe.
        if probe_reserved:
            chunk_results = await fan_out(coros, probe_reserved=True)
        else:
            chunk_results = await fan_out(coros)
        throw_if_cancelled(chunk_results)
        updates = [
            _record_target(target, result)
            for target, result in zip(targets, chunk_results, strict=True)
        ]
        settled = await gather_bounded(updates, max_concurrent=10)
        for result in settled:
            if isinstance(result, BaseException):
                update_failed = True
                log.error("Enforcement target ctx failed: %s", result)
        if warn_clear_user:
            landed = [
                as_int(target.get("chat_id"))
                for target, result in zip(targets, chunk_results, strict=True)
                if result is None or is_benign_telegram_error(result)
            ]
            await _clear_landed_warns(warn_clear_user, landed)
        results.extend(chunk_results)
        processed += len(targets)
        # * A short claim means no more targets of this run are available
        # * right now, so there is nothing left to deliver in later chunks.
        if len(targets) < chunk_size:
            break

    if operation == "reconcile" and not update_failed:
        remaining = [
            result
            for result in results
            if isinstance(result, BaseException)
            and not is_benign_telegram_error(result)
        ]
        # * Empty results mean no unban was delivered (the circuit opened or
        # * no target was claimable). Closing the kick then hides a live ban.
        if results and not remaining:
            await _close_repaired_kick(as_int(action.get("action_id")))


async def _deliver(
    bot: Client,
    action_type: str,
    chat_id: int,
    user_id: int,
    operation: str,
    expires_at: datetime | None = None,
) -> None:
    """Apply or lift one decision in one chat."""
    if chat_id == 0:
        return
    async with asyncio.timeout(TELEGRAM_ACTION_TIMEOUT):
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
            await bot.unban_chat_member(chat_id, user_id)
        else:
            await bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True,
                    can_manage_topics=True,
                ),
            )


async def _clear_landed_warns(user_id: int, chat_ids: list[int]) -> None:
    """Clear the warnings of chats where an automated ban actually landed."""
    if user_id <= 0 or not chat_ids:
        return
    try:
        await db.warns_db.clear_warns_for_chats(user_id, chat_ids)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Warn cleanup failed for user=%d after enforcement", user_id)


async def _close_repaired_kick(action_id: int) -> None:
    """Mark a repaired kick completed once its unban has landed."""
    if action_id <= 0:
        return
    try:
        await db.kicks_db.mark_kick_completed(action_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Kick status restore failed for action=%s", action_id)


async def _record_target(target: dict[str, object], result: object) -> None:
    """Persist one target result and schedule a bounded retry on failure."""
    target_id = as_int(target.get("id"))
    attempts = as_int(target.get("attempt_count"))
    if target_id <= 0:
        return
    if result is None:
        await db.enforcement_db.complete_target(
            target_id, status="succeeded", outcome="succeeded"
        )
        return
    if isinstance(result, BaseException) and is_permanent_telegram_error(result):
        # * A missing right or a lost membership cannot recover on its own.
        # * The target is terminal so the failure stays visible to an
        # * operator; retrying it would only repeat the same refusal.
        await db.enforcement_db.complete_target(
            target_id,
            status="failed",
            outcome="failed",
            error_kind="permanent",
            error_detail=str(result),
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
