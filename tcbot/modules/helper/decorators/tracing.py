# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Execution tracer for handler entry/exit logging."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from telegram.ext import ContextTypes

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from tcbot.utils.logger import bind_request_context, clear_request_context
from tcbot.utils.time_and_date import elapsed_ms, monotonic

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


def log_execution[R](
    func: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Wrap a handler to emit entry / exit / exception traces at DEBUG level."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> R:
        """Emit entry, exit, and exception traces at DEBUG level around ``func``."""
        uid = update.effective_user.id if update.effective_user else "?"
        name = func.__name__
        t0 = monotonic()
        # * Bind first so even the entry line carries request context; the
        # * finally below clears it so pooled tasks never leak one update's
        # * IDs into the next (contextvars are task-local per update).
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        bind_request_context(
            update_id=getattr(update, "update_id", None),
            user_id=getattr(user, "id", None),
            chat_id=getattr(chat, "id", None),
        )
        log.debug("[%s] uid=%s enter", name, uid)
        try:
            result = await func(update, ctx)
            log.debug("[%s] uid=%s ok (%.1fms)", name, uid, elapsed_ms(t0))
            return result
        except Exception:
            log.exception("[%s] uid=%s raised after %.1fms", name, uid, elapsed_ms(t0))
            raise
        finally:
            clear_request_context()

    return _wrapper
