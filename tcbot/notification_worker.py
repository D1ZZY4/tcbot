# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Retry the review-card edits that Telegram refused in the handler."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from pyrogram import Client

from tcbot import database as db
from tcbot.database.types import as_int
from tcbot.modules.helper.pipelines.errors.exceptions import (
    TRANSPORT_TIMEOUT_ERRORS,
    is_bad_request,
    is_forbidden,
    is_invalid_button_user,
)
from tcbot.modules.helper.rich.edit import edit_rich
from tcbot.modules.helper.rich.msg import html_message
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.circuit_breaker import CircuitState
from tcbot.utils.i18n import resolve_locale, t
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_ACTION_TIMEOUT

log = get_logger(__name__)

_BOT: Client | None = None
_MAX_TASKS_PER_TICK: int = 10
_MAX_ATTEMPTS: int = 5
_RETRY_DELAY = timedelta(minutes=5)


def configure(bot: Client) -> None:
    """Attach the live bot the scheduled job must use."""
    global _BOT
    _BOT = bot


async def run() -> None:
    """APScheduler entry point: drain due review-card edits once."""
    if _BOT is None:
        log.debug("Notification worker skipped: no bot is attached.")
        return
    try:
        await run_once(_BOT)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Notification worker tick failed.")


async def run_once(bot: Client) -> None:
    """Claim and process the due card edits."""
    # * A card edit skipped by an open circuit never reached Telegram.
    # * Leaving the tasks unclaimed preserves their retry budget for the
    # * next tick after the circuit recovers.
    state = _cb.telegram.state
    if state is CircuitState.OPEN:
        log.warning(
            "Notification worker paused: Telegram circuit is OPEN; "
            "queued card edits stay pending for the next tick."
        )
        return
    # * HALF_OPEN admits one probe. When CLOSED, claim no more edits than the
    # * breaker can still admit: a mid-batch opening would skip the remaining
    # * tasks after their attempt counters were already consumed at claim time.
    probe_reserved = False
    if state is CircuitState.HALF_OPEN:
        # * Claiming increments the retry counter. Reserve the single probe
        # * before that write: a later rejection would otherwise spend an
        # * attempt without any Telegram call and can terminalize a decided
        # * card after a few ticks of probe contention.
        if not _cb.telegram.try_acquire():
            log.warning(
                "Notification worker paused: Telegram recovery probe is in flight; "
                "queued card edits keep their retry budget."
            )
            return
        probe_reserved = True
        limit = 1
    else:
        limit = min(_MAX_TASKS_PER_TICK, max(1, _cb.telegram.admission_headroom))
    try:
        tasks = await db.notifications_db.claim_due_tasks(
            limit, retry_after=_RETRY_DELAY
        )
        for task in tasks:
            try:
                await _process_task(bot, task, probe_reserved=probe_reserved)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception(
                    "Notification task %s failed; leaving it for the next tick.",
                    task.get("id"),
                )
                # * A failure before the retry decision (the task/action read)
                # * used to leave the row pending forever while the claim kept
                # * advancing its attempt count. Enforce the same ceiling here so
                # * the row reaches a terminal state and stops consuming a slot.
                task_id = as_int(task.get("id"))
                if task_id > 0 and as_int(task.get("attempts")) >= _MAX_ATTEMPTS:
                    try:
                        await db.notifications_db.complete_task(
                            task_id,
                            state="failed",
                            error=f"worker error: {exc}",
                            expected_attempts=as_int(task.get("attempts")),
                            expected_message_id=as_int(task.get("message_id")),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception(
                            "Notification task %s could not be marked failed.",
                            task_id,
                        )
    finally:
        # * An empty claim, a skipped card, or a worker error must not strand
        # * the reserved probe for every other circuit participant.
        if probe_reserved:
            _cb.telegram.release_probe()


def _card_is_still_decidable(action: dict[str, object], message_id: int) -> bool:
    """Return True when the card still belongs to a live review.

    A queued edit is normally written after a decision, so the card must be
    closed. The one exception is a card that is still the live review of an
    active decision with a pending appeal: closing it would remove the only
    way to decide that appeal.
    """
    return (
        str(action.get("status") or "") == "active"
        and action.get("has_pending_appeal") is True
        and as_int(action.get("review_message_id")) == message_id
    )


async def _group_locale(chat_id: int) -> str:
    """Resolve the locale of the card destination."""
    try:
        group_locale = await db.groups_db.get_group_locale(chat_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Notification locale read failed for %d: %s", chat_id, exc)
        group_locale = None
    return resolve_locale(
        chat_type="supergroup",
        group_locale=group_locale if isinstance(group_locale, str) else None,
    )


async def _process_task(
    bot: Client, task: dict[str, object], *, probe_reserved: bool = False
) -> None:
    """Edit one card, or record why the retry cannot succeed."""
    task_id = as_int(task.get("id"))
    action_id = as_int(task.get("action_id"))
    chat_id = as_int(task.get("chat_id"))
    message_id = as_int(task.get("message_id"))
    attempts = as_int(task.get("attempts"))
    next_retry_at = task.get("next_retry_at")

    async def _release_claim() -> None:
        """Return the claim when no Telegram edit has been confirmed."""
        try:
            await db.notifications_db.release_claim(
                task_id,
                expected_attempts=attempts,
                expected_message_id=message_id,
                expected_next_retry_at=next_retry_at,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Review-card claim release failed for task=%s", task_id)

    async def _complete(**kwargs: Any) -> None:
        """Settle only the claim that started this edit."""
        await db.notifications_db.complete_task(
            task_id,
            expected_message_id=message_id,
            **kwargs,
        )

    if task_id <= 0:
        return
    # * The claim is charged before this function starts. Every exit, including
    # * cancellation during either database read below, must settle or return it.
    probe_acquired = False
    edit_confirmed = False
    try:
        if action_id <= 0 or chat_id == 0 or message_id <= 0:
            # * A row with a missing identifier can never succeed, and leaving
            # * it pending makes the claim advance its attempt count forever.
            # * Record the terminal state so it stops consuming a worker slot.
            await _complete(
                state="failed",
                error="the task carries an invalid action, chat, or message id",
                expected_attempts=attempts,
            )
            return
        action = await db.notifications_db.load_task_action(task_id)
        if action is None or _card_is_still_decidable(action, message_id):
            await _complete(state="skipped", expected_attempts=attempts)
            return
        locale = await _group_locale(chat_id)
        text = t("appeals.review.card_closed", locale, plain=True)
        # * In HALF_OPEN run_once reserves the sole probe before claiming, because
        # * the claim itself already consumes a retry attempt. A reserved slot must
        # * not reject itself here. In CLOSED a second worker could otherwise issue
        # * a concurrent probe, so the call site still admits each edit.
        if not probe_reserved and not _cb.telegram.try_acquire():
            log.warning(
                "Review-card edit for action=%d skipped: Telegram circuit is not "
                "admitting calls.",
                action_id,
            )
            # * The claim already charged an attempt. Without releasing it, a
            # * card skipped during an outage reaches the attempt ceiling and is
            # * recorded as failed even though Telegram never saw an edit.
            await _release_claim()
            return
        probe_acquired = not probe_reserved
        try:
            async with asyncio.timeout(TELEGRAM_ACTION_TIMEOUT):
                await edit_rich(
                    bot,
                    chat_id,
                    message_id,
                    html_message(text),
                    # * An explicit empty keyboard is required to strip the
                    # * Approve/Reject buttons from a decided card.
                    clear_markup=True,
                )
        except Exception as exc:
            detail = str(exc).lower()
            # * Match fan_out: only a transport failure trips the breaker. A
            # * service answer, including RetryAfter and BadRequest, does not;
            # * otherwise five rate-limit replies would stall every fan-out.
            if isinstance(exc, TRANSPORT_TIMEOUT_ERRORS) or (
                isinstance(exc, OSError) and not is_bad_request(exc)
            ):
                _cb.telegram.record_failure()
            else:
                _cb.telegram.release_probe(reached_service=True)
            if (
                is_forbidden(exc)
                or is_invalid_button_user(exc)
                or (
                    is_bad_request(exc)
                    and ("not found" in detail or "message_id_invalid" in detail)
                )
            ):
                await _complete(
                    state="skipped",
                    error=str(exc),
                    expected_attempts=attempts,
                )
                return
            if is_bad_request(exc) and "not modified" in detail:
                # * Telegram already has the closed text, so the edit landed from
                # * the operator's point of view. A failed settlement must not
                # * fall through to run_once's ceiling handler, which would mark
                # * a delivered card as failed.
                edit_confirmed = True
                try:
                    await _complete(state="sent", expected_attempts=attempts)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception(
                        "Review-card edit was already current for action=%d but its "
                        "settlement write failed; leaving the task pending.",
                        action_id,
                    )
                return
            retry = attempts < _MAX_ATTEMPTS
            log.warning(
                "Review-card edit failed for action=%d chat=%d message=%d "
                "(attempt %d/%d): %s",
                action_id,
                chat_id,
                message_id,
                attempts,
                _MAX_ATTEMPTS,
                exc,
            )
            await _complete(
                state="failed" if not retry else "pending",
                error=str(exc),
                retry_after=_RETRY_DELAY if retry else None,
                expected_attempts=attempts,
            )
            return
        _cb.telegram.record_success()
        # * The Telegram edit has landed. From here on, cancellation belongs to
        # * the settlement write, not to the claim: releasing it would grant a
        # * sixth attempt and re-edit an already-closed card.
        edit_confirmed = True
        try:
            await _complete(state="sent", expected_attempts=attempts)
        except asyncio.CancelledError:
            raise
        except Exception:
            # * The edit already landed. A failed settlement must not reach
            # * run_once's ceiling handler, which would record a delivered card
            # * as failed. Leave the claim pending for the next tick.
            log.exception(
                "Review-card edit landed for action=%d but its settlement write "
                "failed; leaving the task pending for retry.",
                action_id,
            )
    except asyncio.CancelledError:
        # * Only a cancellation before Telegram confirmed the edit returns the
        # * claim. Once the edit landed, its settlement may still be retried;
        # * releasing the claim would restore a spent attempt and re-edit a
        # * card the operator already sees as closed. A probe reserved by
        # * run_once stays owned by run_once; only a probe taken here is released.
        if not edit_confirmed:
            await _release_claim()
            if probe_acquired:
                _cb.telegram.release_probe()
        raise
