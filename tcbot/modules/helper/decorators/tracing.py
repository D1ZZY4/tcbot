# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Execution tracer for handler entry/exit logging."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from pyrogram import ContinuePropagation

from tcbot.modules.helper.context import Ctx
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from tcbot.utils.logger import bind_request_context, clear_request_context
from tcbot.utils.time_and_date import elapsed_ms, monotonic

log = get_logger(__name__)


def log_execution[R](
    func: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Wrap a handler to emit entry / exit / exception traces at DEBUG level."""

    @functools.wraps(func)
    async def _wrapper(ctx: Ctx) -> R:
        """Emit entry, exit, and exception traces at DEBUG level around ``func``."""
        user = getattr(ctx, "effective_user", None)
        chat = getattr(ctx, "effective_chat", None)
        uid = getattr(user, "id", None)
        t0 = monotonic()
        # * Bind first so even the entry line carries request context; the
        # * finally below clears it so pooled tasks never leak one ctx's
        # * IDs into the next (contextvars are task-local per ctx).
        bind_request_context(
            update_id=getattr(ctx, "update_id", None),
            user_id=uid,
            chat_id=getattr(chat, "id", None),
        )
        debug_on = log.is_debug_enabled()
        name = func.__name__
        if debug_on:
            log.debug("[%s] uid=%s enter", name, "?" if uid is None else uid)
        try:
            result = await func(ctx)
            if debug_on:
                log.debug(
                    "[%s] uid=%s ok (%.1fms)",
                    name,
                    "?" if uid is None else uid,
                    elapsed_ms(t0),
                )
            return result
        except ContinuePropagation:
            # * Dispatcher hand-off, not a failure: the next handler owns the
            # * update. Keep the trace at DEBUG like every other exit line.
            if debug_on:
                log.debug(
                    "[%s] uid=%s passed on after %.1fms",
                    name,
                    "?" if uid is None else uid,
                    elapsed_ms(t0),
                )
            raise
        except Exception:
            log.exception(
                "[%s] uid=%s raised after %.1fms",
                name,
                "?" if uid is None else uid,
                elapsed_ms(t0),
            )
            raise
        finally:
            clear_request_context()

    return _wrapper
