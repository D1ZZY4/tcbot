# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Retry the review-card edits that Telegram refused in the handler."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from telegram.error import BadRequest, Forbidden

from tcbot import database as db
from tcbot.database.types import as_int
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.circuit_breaker import CircuitState
from tcbot.utils.i18n import resolve_locale, t
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_ACTION_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

_BOT: Bot | None = None
_MAX_TASKS_PER_TICK: int = 10
_MAX_ATTEMPTS: int = 5
_RETRY_DELAY = timedelta(minutes=5)


def configure(bot: Bot) -> None:
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


async def run_once(bot: Bot) -> None:
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
    if state is CircuitState.HALF_OPEN:
        limit = 1
    else:
        limit = min(_MAX_TASKS_PER_TICK, max(1, _cb.telegram.admission_headroom))
    tasks = await db.notifications_db.claim_due_tasks(limit, retry_after=_RETRY_DELAY)
    for task in tasks:
        try:
            await _process_task(bot, task)
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


async def _process_task(bot: Bot, task: dict[str, object]) -> None:
    """Edit one card, or record why the retry cannot succeed."""
    task_id = as_int(task.get("id"))
    action_id = as_int(task.get("action_id"))
    chat_id = as_int(task.get("chat_id"))
    message_id = as_int(task.get("message_id"))
    attempts = as_int(task.get("attempts"))

    async def _complete(**kwargs: Any) -> None:
        """Settle only the claim that started this edit."""
        await db.notifications_db.complete_task(
            task_id,
            expected_message_id=message_id,
            **kwargs,
        )

    if task_id <= 0:
        return
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
    # * Reserve the breaker slot at the call site. run_once only limits how
    # * many tasks are claimed; without this guard a second worker can issue a
    # * concurrent HALF_OPEN call and close the circuit while the other probe
    # * is still in flight. A rejected call leaves the task for a later tick.
    if not _cb.telegram.try_acquire():
        log.warning(
            "Review-card edit for action=%d skipped: Telegram circuit is not "
            "admitting calls.",
            action_id,
        )
        # * A rejected slot consumes the claim's attempt without any Telegram
        # * call. Under a flapping breaker the row would otherwise stay pending
        # * forever while each claim advanced its counter past the ceiling.
        if attempts >= _MAX_ATTEMPTS:
            await _complete(
                state="failed",
                error="Telegram circuit never admitted the card edit",
                expected_attempts=attempts,
            )
        return
    try:
        async with asyncio.timeout(TELEGRAM_ACTION_TIMEOUT):
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=None,
                reply_markup=None,
            )
    except asyncio.CancelledError:
        _cb.telegram.release_probe()
        raise
    except Exception as exc:
        detail = str(exc).lower()
        # * A Telegram refusal means the service answered. Like fan_out, do
        # * not count it toward the breaker; only transport failures do.
        if isinstance(exc, (BadRequest, Forbidden)):
            _cb.telegram.release_probe(reached_service=True)
        else:
            _cb.telegram.record_failure()
        if isinstance(exc, Forbidden) or (
            isinstance(exc, BadRequest)
            and ("not found" in detail or "message_id_invalid" in detail)
        ):
            await _complete(
                state="skipped",
                error=str(exc),
                expected_attempts=attempts,
            )
            return
        if isinstance(exc, BadRequest) and "not modified" in detail:
            await _complete(state="sent", expected_attempts=attempts)
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
    await _complete(state="sent", expected_attempts=attempts)
