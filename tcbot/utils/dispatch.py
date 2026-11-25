# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bounded concurrency dispatcher for multi-group Telegram and database work."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.pipelines.errors.exceptions import (
    TRANSPORT_TIMEOUT_ERRORS,
    is_api_refusal,
    is_bad_request,
)
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable, Sequence

log = get_logger(__name__)

# * Telegram allows 30 msg/s globally; 10 concurrent is safe and fast.
_MAX_CONCURRENT: int = 10

# * Kurigram reports its own deadlines as RPCError subclasses, not as the
# * builtin TimeoutError. Both forms are transport stalls and must count
# * against the breaker; otherwise a HALF_OPEN probe that times out is
# * mistaken for a healthy service and closes the circuit prematurely.
_FANOUT_TIMEOUTS: tuple[type[BaseException], ...] = TRANSPORT_TIMEOUT_ERRORS

# * Substrings inside Telegram refusals that indicate the action had nothing
# * to do: the user was not in the target chat, the chat no longer exists, or
# * the target cannot be acted on. These are real Telegram API responses (not
# * exceptions we should retry), but they are not "failures" in the sense the
# * operator cares about. The list is intentionally conservative: only
# * patterns observed in production logs. Each entry is stored in upper-case;
# * the matcher in ``is_benign_telegram_error`` upper-cases the Telegram
# * message before substring search.
_BENIGN_BAD_REQUEST_SUBSTRINGS: tuple[str, ...] = (
    "USER_NOT_PARTICIPANT",  # user was not in the target group
    "USER_ID_INVALID",  # bad user id at protocol level
    "CHAT_NOT_FOUND",  # group was deleted
    "PEER_ID_INVALID",  # user or chat id rejected by Telegram
    "USER_NOT_FOUND",  # Telegram does not know the user
    "USER_IS_A_BOT",  # bot users cannot be banned/muted/etc.
    "USER_IS_ANONYMOUS",  # GroupAnonymousBot placeholder
    "PARTICIPANT_ID_INVALID",  # user not a participant of the chat
)

# * Substrings that mean the action did not land and a retry cannot fix it:
# * the bot lost the rights or the chat, so an operator has to restore access.
# * These are permanent failures, distinct from a benign no-op and from a
# * transient timeout. The enforcement ledger records them as failed with no
# * retry deadline, so they stay visible instead of being counted as applied.
_PERMANENT_BAD_REQUEST_SUBSTRINGS: tuple[str, ...] = (
    "CHAT_ADMIN_REQUIRED",  # bot was demoted or lost its admin rights
    "CHAT_WRITE_FORBIDDEN",  # bot may not write in the chat
    "NOT_ENOUGH_RIGHTS",  # bot lacks the right the operation needs
    "BOT_WAS_KICKED",  # bot is no longer a member of the chat
    "BOT_IS_NOT_A_MEMBER",  # bot was removed from the chat
)


_NON_ALNUM_RE = re.compile(r"[\W_]+")


def _normalize(s: str) -> str:
    """Strip every non-alphanumeric character for benign-match comparison."""
    return _NON_ALNUM_RE.sub("", s)


# * Precomputed once: the matchers below run per failure, and rebuilding
# * these strings on every error is pure waste.
_BENIGN_NORMALIZED: tuple[str, ...] = tuple(
    _normalize(s) for s in _BENIGN_BAD_REQUEST_SUBSTRINGS
)
_PERMANENT_NORMALIZED: tuple[str, ...] = tuple(
    _normalize(s) for s in _PERMANENT_BAD_REQUEST_SUBSTRINGS
)


# ──────────────── Throttled Multi-Group Dispatcher ──────────────── #


async def fan_out[T](
    coros: Sequence[Awaitable[T]],
    *,
    max_concurrent: int = _MAX_CONCURRENT,
    probe_reserved: bool = False,
) -> list[T | BaseException]:
    """Run coros concurrently up to max_concurrent at once.

    Integrates the Telegram circuit breaker: slots that run while the circuit
    is OPEN are skipped immediately (returning a ``CircuitOpenError``) instead
    of firing a Telegram request that will time out. Builtin timeouts, network
    errors, and the client's own RPC timeout errors trip the circuit; API
    refusals (403, 400, etc.) are expected responses and do not affect it.

    Regular failures are returned as list elements instead of raising, but
    ``asyncio.CancelledError`` always propagates so task cancellation (for
    example during shutdown) is never coerced into per-group failure data.

    Tasks are admitted lazily through the semaphore so the number of in-flight
    Telegram calls stays bounded. Callers may pass already-created coroutine
    objects; a coroutine skipped by the open circuit is explicitly closed.

    A caller that already reserved the single HALF_OPEN probe passes
    ``probe_reserved=True`` with exactly one coroutine. The slot then skips its
    own reservation because the caller holds it; the usual outcome handling
    still settles the breaker. Every other caller remains blocked while that
    probe is in flight.
    """
    n = len(coros)
    if n == 0:
        if probe_reserved:
            # * No slot will settle a probe reserved for an empty fan-out.
            _cb.telegram.release_probe()
        return []

    if max_concurrent < 1:
        max_concurrent = 1

    async def _run_one(coro: Awaitable[T]) -> tuple[T | BaseException, bool]:
        if not probe_reserved and not _cb.telegram.try_acquire():
            if inspect.iscoroutine(coro):
                coro.close()
            return _cb.CircuitOpenError("Telegram circuit is OPEN; call skipped."), True
        try:
            result = await coro
            _cb.telegram.record_success()
            return result, False
        except _FANOUT_TIMEOUTS as exc:
            # * Callers bound individual deliveries with asyncio.timeout,
            # * and the client raises its own deadline errors. Both are
            # * transport stalls and have to count against the circuit.
            _cb.telegram.record_failure()
            log.debug("fan_out: timeout (counted against circuit): %s", exc)
            return exc, False
        except OSError as exc:
            # ! CRITICAL: a 400 is an API refusal (user not in chat, chat
            # ! gone), never congestion. Kurigram reports refusals as
            # ! RPCError, not OSError, so none reach this branch. Counting
            # ! refusals tripped the breaker after five consecutive ones
            # ! and skipped the remaining groups unenforced.
            _cb.telegram.record_failure()
            log.debug("fan_out: network error (counted against circuit): %s", exc)
            return exc, False
        except asyncio.CancelledError:
            _cb.telegram.release_probe()
            raise
        except Exception as exc:
            # * A refusal proves the service answered, so the transport is
            # * healthy and a HALF_OPEN probe closes instead of stranding
            # * the circuit. RPC timeouts were settled above.
            _cb.telegram.release_probe(reached_service=True)
            log.debug(
                "fan_out: coroutine failed (not counted against circuit): %s", exc
            )
            return exc, False

    if n == 1:
        single_res, was_skipped = await _run_one(coros[0])
        if was_skipped:
            log.warning(
                "fan_out: Telegram circuit OPEN; skipped 1 slot(s) to avoid timeouts."
            )
        return [single_res]

    results: list[T | BaseException] = [None] * n  # type: ignore[list-item]
    next_idx = 0
    skipped = 0

    async def _worker() -> None:
        nonlocal next_idx, skipped
        while next_idx < n:
            idx = next_idx
            next_idx += 1
            res, was_skipped = await _run_one(coros[idx])
            results[idx] = res
            if was_skipped:
                skipped += 1

    worker_count = min(max_concurrent, n)
    try:
        await asyncio.gather(*(_worker() for _ in range(worker_count)))
    except asyncio.CancelledError:
        for i in range(next_idx, n):
            coro = coros[i]
            if inspect.iscoroutine(coro):
                coro.close()
        raise
    # * One summary line per call instead of one warning per skipped slot:
    # * an open-circuit fan-out over N groups used to emit N identical lines.
    if skipped:
        log.warning(
            "fan_out: Telegram circuit OPEN; skipped %d slot(s) to avoid timeouts.",
            skipped,
        )
    return results


async def gather_bounded[T](
    coros: Sequence[Awaitable[T]],
    *,
    max_concurrent: int = _MAX_CONCURRENT,
) -> list[T | BaseException]:
    """Run coros with bounded concurrency, without the Telegram circuit breaker.

    Same result contract as :func:`fan_out` (order preserved, regular
    failures returned as list elements, ``asyncio.CancelledError`` always
    propagated) but with no circuit interaction. Use it for pure database
    bursts where tripping or reading the Telegram breaker would be wrong,
    such as bulk deactivations during cleanup.
    """
    n = len(coros)
    if n == 0:
        return []

    if max_concurrent < 1:
        max_concurrent = 1

    if n == 1:
        try:
            return [await coros[0]]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return [exc]

    results: list[T | BaseException] = [None] * n  # type: ignore[list-item]
    next_idx = 0

    async def _worker() -> None:
        nonlocal next_idx
        while next_idx < n:
            idx = next_idx
            next_idx += 1
            try:
                results[idx] = await coros[idx]
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                results[idx] = exc

    worker_count = min(max_concurrent, n)
    try:
        await asyncio.gather(*(_worker() for _ in range(worker_count)))
    except asyncio.CancelledError:
        for i in range(next_idx, n):
            coro = coros[i]
            if inspect.iscoroutine(coro):
                coro.close()
        raise
    return results


def throw_if_cancelled(results: Iterable[object]) -> None:
    """Re-raise the first ``asyncio.CancelledError`` in gather results.

    Every ``asyncio.gather(..., return_exceptions=True)`` site that must not
    coerce shutdown into data repeats this loop; centralising it keeps
    cancellation semantics identical everywhere. Regular exceptions are left
    untouched for the caller to inspect.
    """
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            raise result


def is_benign_telegram_error(exc: BaseException) -> bool:
    """Return True if the exception is a known-benign Telegram API refusal.

    A "benign" refusal is one where there was nothing to do: the user was
    never in the chat, the chat was deleted, or the target cannot be acted
    on. These are real Telegram responses (the API call did fail), but they
    are not "failures" in the moderation sense.

    Matching uses a "normalized" form where non-alphanumeric characters are
    stripped (so the API code ``USER_NOT_PARTICIPANT`` matches the
    human-readable ``User not participant`` a Telegram client may return).
    A missing
    permission is not benign; see :func:`is_permanent_telegram_error`.
    """
    if is_bad_request(exc):
        normalized = _normalize(str(exc).upper())
        for target in _BENIGN_NORMALIZED:
            if target in normalized:
                return True
    return False


def is_permanent_telegram_error(exc: BaseException) -> bool:
    """Return True when a Telegram refusal cannot succeed on retry.

    The bot lost the rights or the membership the operation needs. The
    action did not land, and retrying cannot change that, so the caller
    records a terminal failure instead of scheduling another attempt. An
    operator has to restore the bot's access before the delivery can work.
    """
    if is_api_refusal(exc):
        normalized = _normalize(str(exc).upper())
        for target in _PERMANENT_NORMALIZED:
            if target in normalized:
                return True
    return False


def count_transient_errors(results: Sequence[object]) -> int:
    """Count fan_out results that represent real (non-benign) failures.

    Benign Telegram API refusals (see ``is_benign_telegram_error``) are
    excluded from the count, so a "user was not in this chat" response
    does not count as a failed group in operator-facing success/failure
    summaries.
    """
    return sum(
        1
        for r in results
        if isinstance(r, BaseException) and not is_benign_telegram_error(r)
    )


def failed_groups(
    groups: Sequence[dict[str, Any]],
    results: Sequence[object],
) -> list[tuple[dict[str, Any], BaseException]]:
    """Return every group whose action raised, with the exception.

    Single owner for the "which groups did not get the action" shape, so
    every federation executor reports its failures the same way.
    """
    return [
        (grp, r)
        for grp, r in zip(groups, results, strict=True)
        if isinstance(r, BaseException)
    ]


def transient_groups(
    groups: Sequence[dict[str, Any]],
    results: Sequence[object],
) -> list[tuple[dict[str, Any], BaseException]]:
    """Return the groups whose action failed for a non-benign reason.

    Benign refusals (the user was never in the chat, the chat is gone)
    are dropped: they are not enforcement failures the operator must act
    on. The shape matches :func:`failed_groups` so both can feed the
    shared applied-summary renderer.
    """
    return [
        (grp, exc)
        for grp, exc in failed_groups(groups, results)
        if not is_benign_telegram_error(exc)
    ]


def first_transient_error(results: Sequence[object]) -> BaseException | None:
    """Return the first non-benign failure in *results*, or None.

    Used to attach a representative exception as ``exc_info`` to the
    error-level fan-out summary so the error reporter classifies the
    record by its real type and shows a traceback instead of the
    misleading "[?] Unknown / Needs a code fix" label. Only non-benign
    (transient) failures qualify; benign refusals are not reportable
    failures.
    """
    for r in results:
        if isinstance(r, BaseException) and not is_benign_telegram_error(r):
            return r
    return None


def log_fanout_error(
    results: Sequence[object],
    *,
    action: str,
    total: int,
    target_id: int,
) -> int:
    """Log the transient-failure summary and return the transient count.

    Single owner for the error-level fan-out line every federation
    executor emits, so the reporter classifies partial failures by their
    real Telegram type. The per-group warning lines and the applied
    summary stay at each call site because their wording differs per
    action; only this error line is shared. Returns the count from
    :func:`count_transient_errors` for the caller's applied arithmetic.
    """
    failed = count_transient_errors(results)
    if failed:
        log.error(
            "%s fan-out had %d/%d transient failures for target=%d",
            action,
            failed,
            total,
            target_id,
            exc_info=first_transient_error(results),
        )
    return failed


# ─────────────────── Federation enforcement outcome ────────────────── #


@dataclass(frozen=True)
class FanoutOutcome:
    """How one federation-wide enforcement action landed.

    ``applied`` counts the groups that accepted the action. A benign
    Telegram refusal (the user was never in the chat, the chat is gone)
    counts as applied: there was nothing to enforce there. Only a
    transient failure counts against the action, and those groups are
    listed in ``transient`` so the operator can name them.
    """

    total: int
    applied: int
    transient: tuple[tuple[dict[str, Any], BaseException], ...]

    @property
    def failed(self) -> int:
        """The number of groups that did not accept the action."""
        return self.total - self.applied


def summarize_fanout(
    groups: Sequence[dict[str, Any]],
    results: Sequence[object],
    *,
    action: str,
    target_id: int,
) -> FanoutOutcome:
    """Report one federation fan-out and return its outcome.

    Single owner for the reporting every federation executor repeats:
    the per-group warning line, the error-level summary that reaches
    ``LOGS_ERRORS``, and the applied/failed arithmetic the user-facing
    summary is built from. The wording of the user-facing summary stays
    with each action, because every action renders it differently.
    """
    transient: list[tuple[dict[str, Any], BaseException]] = []
    for grp, exc in zip(groups, results, strict=True):
        if isinstance(exc, BaseException):
            log.warning(
                "%s enforcement failed for user=%d in group=%s (%d): %s",
                action,
                target_id,
                grp.get("title", ""),
                grp["chat_id"],
                exc,
            )
            if not is_benign_telegram_error(exc):
                transient.append((grp, exc))
    failed = len(transient)
    if failed:
        log.error(
            "%s fan-out had %d/%d transient failures for target=%d",
            action,
            failed,
            len(groups),
            target_id,
            exc_info=transient[0][1],
        )
    return FanoutOutcome(
        total=len(groups),
        applied=len(groups) - failed,
        transient=tuple(transient),
    )
