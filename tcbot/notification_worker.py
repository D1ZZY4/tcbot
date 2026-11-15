# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Retry the review-card edits that Telegram refused in the handler."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from telegram.error import BadRequest, Forbidden

from tcbot import database as db
from tcbot.utils.i18n import resolve_locale, t
from tcbot.utils.logger import get_logger

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
    tasks = await db.notifications_db.claim_due_tasks(
        _MAX_TASKS_PER_TICK, retry_after=_RETRY_DELAY
    )
    for task in tasks:
        try:
            await _process_task(bot, task)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Notification task %s failed; leaving it for the next tick.",
                task.get("id"),
            )


def _as_int(value: object) -> int:
    """Read a database integer without trusting its runtime type."""
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
        and _as_int(action.get("review_message_id")) == message_id
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
    task_id = _as_int(task.get("id"))
    action_id = _as_int(task.get("action_id"))
    chat_id = _as_int(task.get("chat_id"))
    message_id = _as_int(task.get("message_id"))
    attempts = _as_int(task.get("attempts"))
    if task_id <= 0 or action_id <= 0 or chat_id == 0 or message_id <= 0:
        return
    action = await db.notifications_db.load_task_action(task_id)
    if action is None or _card_is_still_decidable(action, message_id):
        await db.notifications_db.complete_task(task_id, state="skipped")
        return
    locale = await _group_locale(chat_id)
    text = t("appeals.review.card_closed", locale, plain=True)
    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=None,
            reply_markup=None,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        detail = str(exc).lower()
        if isinstance(exc, Forbidden) or (
            isinstance(exc, BadRequest)
            and ("not found" in detail or "message_id_invalid" in detail)
        ):
            await db.notifications_db.complete_task(
                task_id, state="skipped", error=str(exc)
            )
            return
        if isinstance(exc, BadRequest) and "not modified" in detail:
            await db.notifications_db.complete_task(task_id, state="sent")
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
        await db.notifications_db.complete_task(
            task_id,
            state="failed" if not retry else "pending",
            error=str(exc),
            retry_after=_RETRY_DELAY if retry else None,
        )
        return
    await db.notifications_db.complete_task(task_id, state="sent")
