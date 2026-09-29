# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error layers: PTB handler errors and asyncio loop exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from tcbot.database import mtproto as mtproto_mod
from tcbot.utils import error_reporter
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

log = get_logger(__name__)

# * Maximum number of characters captured from a message in error-handler context.
_ERROR_CONTEXT_TEXT_LEN: int = 120

# * Strong references to in-flight async error-report tasks. Without this, the
# * fire-and-forget task scheduled in the handler below can be garbage collected
# * before it runs, silently dropping the report (mirrors logger._tg_tasks).
_asyncio_report_tasks: set[asyncio.Task[None]] = set()


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch all unhandled PTB handler exceptions and report them to the logs-errors channel."""
    exc = ctx.error
    if exc is None:
        return

    # * Circuit-open errors are expected when a downstream service is temporarily
    # * unreachable. Reporting every update's CircuitOpenError would flood the
    # * error channel with identical messages; the breaker already logs transitions.
    if isinstance(exc, CircuitOpenError):
        log.warning("Handler aborted: %s", exc)
        return

    # * Build context string from the update for extra detail
    context_parts: list[str] = []
    if isinstance(update, Update):
        if update.effective_user:
            u = update.effective_user
            context_parts.append(f"User: {u.first_name} ({u.id})")
        if update.effective_chat:
            c = update.effective_chat
            context_parts.append(f"Chat: {c.title or 'DM'} ({c.id})")
        if update.effective_message and update.effective_message.text:
            context_parts.append(
                f"Text: {update.effective_message.text[:_ERROR_CONTEXT_TEXT_LEN]}"
            )
        elif update.callback_query:
            context_parts.append(f"CBQ data: {update.callback_query.data}")

    # * Scrub before logging: message excerpts can carry user-pasted secrets
    # * into persistent console logs. The shipped report path scrubs again
    # * (idempotent markers), so this only hardens the console copy.
    context_str = (
        error_reporter.scrub_text(" | ".join(context_parts)) if context_parts else None
    )

    # * Only the numeric update ID is logged, never the raw Update repr: message
    # * text can carry user-pasted secrets into persistent console logs, while
    # * the shipped report path is scrubbed separately by the error reporter.
    update_id = update.update_id if isinstance(update, Update) else "?"
    log.error(
        "Unhandled exception for update %s%s",
        update_id,
        f" | {context_str}" if context_str else "",
        exc_info=exc,
    )

    await error_reporter.report_exc(exc, context=context_str)


def _make_asyncio_exc_handler(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[asyncio.AbstractEventLoop, dict], None]:
    """Return a synchronous asyncio exception handler that mirrors errors to the error reporter."""

    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        """Forward asyncio exceptions to the error reporter and module logger."""
        exc = context.get("exception")
        msg = context.get("message", "Unhandled asyncio exception")
        future = context.get("future") or context.get("task")
        detail = f"{msg} | Task: {future!r}" if future else msg

        # * Mirror to module logger so nothing is silently swallowed.
        log.error("[asyncio] %s%s", detail, f" - {exc}" if exc else "")

        # * A dead shared MTProto session crashes Pyrogram's background
        # * tasks in a tight loop (406 AUTH_KEY_DUPLICATED from a duplicate
        # * instance). Park it once here; later repeats hit the dead-guard
        # * and stay silent, so one incident ships one loud card instead of
        # * a flood (each Task-NNNN used to defeat the fingerprint dedupe).
        if exc is not None and mtproto_mod.is_auth_key_duplicated(exc):
            if mtproto_mod.is_auth_dead():
                log.debug("[asyncio] duplicate AuthKeyDuplicated suppressed.")
                return
            try:
                park = lp.create_task(mtproto_mod.handle_auth_failure())
                _asyncio_report_tasks.add(park)
                park.add_done_callback(_asyncio_report_tasks.discard)
            except Exception as err:
                log.debug("Failed to schedule MTProto park task: %s", err)
            # * Fall through: this first occurrence still ships loudly via
            # * the normal report path below.

        # * Schedule async report on the running loop, keeping a strong reference
        # * until the task completes so it cannot be garbage collected mid-flight.
        try:
            task = lp.create_task(
                error_reporter.report_exc(exc or RuntimeError(detail), context=detail)
            )
            _asyncio_report_tasks.add(task)
            task.add_done_callback(_asyncio_report_tasks.discard)
        except Exception as err:
            log.debug("Failed to schedule async error report: %s", err)

    return handler
