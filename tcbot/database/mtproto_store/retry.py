# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto store write retry: transient-error detection and bounded backoff."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pymongo.errors import WriteConcernError

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

# * Maximum retries for transient write concern errors (e.g. replica set
# * failover). Each retry waits exponentially: 0.5s, 1s, 2s.
_MAX_WRITE_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 0.5

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto_store")


def _is_transient_write_error(exc: BaseException) -> bool:
    """Return True when *exc* is a retryable MongoDB write concern error."""
    return isinstance(exc, WriteConcernError) and "RetryableWriteError" in getattr(
        exc, "details", {}
    ).get("errorLabels", [])


async def _retry_write(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Execute a fresh coroutine from *coro_factory* with retries on transient WriteConcernError.

    Pyrogram's ``handle_updates()`` background task persists update states
    through this store.  A transient replica-set failover (code 11602 /
    ``InterruptedDueToReplStateChange``) raises ``WriteConcernError`` with
    the ``RetryableWriteError`` label.  Because the task is fire-and-forget,
    the exception is never retrieved and the event loop reports it as an
    unhandled task exception.

    Retrying transparently keeps the session alive through brief replica-set
    elections without flooding the error channel.

    *coro_factory* must return a **new** coroutine on each call so retries
    re-execute the operation instead of re-awaiting a spent coroutine.
    """
    last_exc: BaseException | None = None
    for attempt in range(_MAX_WRITE_RETRIES):
        try:
            return await coro_factory()
        except BaseException as exc:
            if not _is_transient_write_error(exc) or attempt == _MAX_WRITE_RETRIES - 1:
                raise
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2**attempt)
            log.debug(
                "MTProto write attempt %d/%d failed (transient): %s; retrying in %.1fs",
                attempt + 1,
                _MAX_WRITE_RETRIES,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    # * pragma: no cover - the loop always returns or raises before reaching here.
    raise last_exc  # type: ignore[misc]
