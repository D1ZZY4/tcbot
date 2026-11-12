# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Async circuit breaker for external service calls (Telegram API, PostgreSQL)."""

from __future__ import annotations

import itertools
from enum import Enum
from typing import TYPE_CHECKING

from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = get_logger(__name__)

_DEFAULT_FAILURE_THRESHOLD: int = 5
_DEFAULT_RECOVERY_TIMEOUT: float = 60.0

# * The attribute that marks an exception as already counted. The marker
# * lives on the exception rather than on the breaker, because a
# * concurrent success on the same breaker would otherwise clear it and
# * the same failure would be counted twice. Built-in exception types do
# * not accept weak references, so a marker object would not work here.
_COUNTED_MARK: str = "_tcbot_counted_failures"

# * Stable per-breaker ids, so the marker on an exception can name the
# * breakers that already counted it.
_BREAKER_MARKER_IDS = itertools.count(1)


class CircuitState(Enum):
    """Operational state of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the circuit is OPEN or HALF_OPEN full."""


class CircuitBreaker:
    """Lightweight async circuit breaker with automatic OPEN/HALF_OPEN/CLOSED transitions.

    Args:
        name: Human-readable service name used in log messages.
        failure_threshold: Transient failures before the circuit opens.
            Successes in CLOSED do not reset the count immediately, so a
            partial outage with interleaved successes can still trip the
            breaker. A long run of consecutive successes (twice the
            threshold) decays the lifetime count so spread-out failures
            over months cannot trip on one new blip.
        recovery_timeout: Seconds to wait in OPEN before allowing a probe.

    """

    __slots__ = (
        "_failure_count",
        "_failure_threshold",
        "_half_open_probe_in_flight",
        "_marker_id",
        "_name",
        "_opened_at",
        "_recovery_timeout",
        "_state",
        "_success_streak",
    )

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = _DEFAULT_RECOVERY_TIMEOUT,
    ) -> None:
        """Initialise a new circuit breaker for the named service."""
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._half_open_probe_in_flight: bool = False
        self._opened_at: float = 0.0
        self._success_streak: int = 0
        self._marker_id: int = next(_BREAKER_MARKER_IDS)

    # ── public API ── #

    @property
    def name(self) -> str:
        """Service name for this circuit."""
        return self._name

    @property
    def state(self) -> CircuitState:
        """Current state; auto-transitions OPEN to HALF_OPEN after timeout."""
        if (
            self._state is CircuitState.OPEN
            and monotonic() - self._opened_at >= self._recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            log.info(
                "Circuit [%s]: OPEN -> HALF_OPEN (recovery probe allowed).",
                self._name,
            )
        return self._state

    def peek_state(self) -> CircuitState:
        """Return the current state WITHOUT triggering the OPEN→HALF_OPEN transition.

        That transition is a side effect of reading ``state``; health and
        monitoring reads must use this so an uptime poll can never flip a
        circuit out of OPEN.
        """
        return self._state

    async def call[T](
        self,
        coro: Awaitable[T],
        *,
        count_failure: Callable[[Exception], bool] | None = None,
    ) -> T:
        """Execute *coro* through the circuit breaker.

        Raises:
            CircuitOpenError: Circuit is OPEN; the call was rejected without
                touching the downstream service.
            Any exception the coroutine itself raises (also recorded as a
                failure; the exception propagates to the caller unchanged).

        When *count_failure* is provided it decides whether the exception
        counts toward opening the circuit. An exception the predicate
        rejects releases the half-open probe without recording a failure,
        matching the Telegram fan-out treatment of API refusals: the
        downstream already answered, so the failure counter keeps its
        transient-failure meaning. When omitted, every exception counts,
        which preserves the historical behaviour for other callers.

        The same exception object is counted once. A helper that already
        runs through this breaker must not be wrapped in a second one: the
        exception travels through both levels unchanged, and counting it
        twice would trip the circuit after fewer real failures than the
        threshold promises.

        """
        if not self.try_acquire():
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise CircuitOpenError(f"Circuit [{self._name}] is OPEN; call rejected.")

        try:
            result: T = await coro
        except Exception as exc:
            if count_failure is not None and not count_failure(exc):
                self._record_reached_service()
            else:
                self._record_failure(exc)
            raise exc from None
        except BaseException:
            # * Cancellation must not leave a HALF_OPEN probe permanently reserved.
            self._release_probe()
            raise

        self._record_success()
        return result

    def try_acquire(self) -> bool:
        """Reserve permission for one call, allowing only one HALF_OPEN probe."""
        state = self.state
        if state is CircuitState.OPEN:
            return False
        if state is CircuitState.HALF_OPEN:
            if self._half_open_probe_in_flight:
                return False
            self._half_open_probe_in_flight = True
        return True

    def release_probe(self, *, reached_service: bool = False) -> None:
        """Release a HALF_OPEN probe.

        With ``reached_service=True`` the downstream answered (a refusal or
        an application error, not a transport failure), so the transport is
        healthy. A HALF_OPEN probe that ends that way closes the circuit:
        leaving it HALF_OPEN would admit one caller at a time and reject
        every concurrent one as if the service were still down.
        """
        if reached_service:
            self._record_reached_service()
        else:
            self._release_probe()

    def record_success(self) -> None:
        """Record a successful outcome (use when not wrapping via call()).

        Intended for callers that manage their own try/except and need to
        inform the circuit without delegating the entire coroutine to it.
        """
        self._record_success()

    def record_failure(self) -> None:
        """Record a failed outcome (use when not wrapping via call()).

        Increments the transient-failure counter and may trip the circuit
        to OPEN.  Intended for callers that manage their own try/except.
        """
        self._record_failure()

    def reset(self) -> None:
        """Force-close the circuit (useful after operator confirms service recovery)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_streak = 0
        self._release_probe()
        log.info("Circuit [%s]: manually reset to CLOSED.", self._name)

    # ── private helpers ── #

    def _already_counted(self, exc: BaseException) -> bool:
        """Return True when this breaker already counted *exc*.

        The marker rides on the exception, so a concurrent success on
        this breaker cannot clear it before the same failure is counted
        a second time on the way out.
        """
        marks = getattr(exc, _COUNTED_MARK, None)
        if marks is None:
            marks = set()
            try:
                setattr(exc, _COUNTED_MARK, marks)
            except AttributeError:
                # * An exception that cannot carry attributes cannot carry
                # * the marker either, so it is counted on every level.
                return False
        if self._marker_id in marks:
            return True
        marks.add(self._marker_id)
        return False

    def _record_success(self) -> None:
        # * Ordinary successes in CLOSED must not reset the counter
        # * immediately. fan_out runs up to 10 slots concurrently: one
        # * success interleaved between concurrent failures would erase
        # * the failure count and the breaker could never trip under a
        # * partial outage. Only a successful HALF_OPEN probe closes and
        # * resets; CLOSED successes accumulate a consecutive streak and
        # * decay the lifetime count only after a sustained healthy run
        # * (twice the threshold), so failures spread over months do not
        # * combine into a spurious trip.
        if self._state is CircuitState.HALF_OPEN:
            log.info("Circuit [%s]: HALF_OPEN -> CLOSED (probe succeeded).", self._name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_streak = 0
        elif self._failure_count > 0:
            self._success_streak += 1
            if self._success_streak >= 2 * self._failure_threshold:
                self._failure_count = 0
                self._success_streak = 0
        self._release_probe()

    def _record_reached_service(self) -> None:
        # * The downstream answered, so the transport is healthy even though
        # * the call did not succeed. A HALF_OPEN probe must close the
        # * circuit here: staying HALF_OPEN admits one caller at a time
        # * and rejects every concurrent one, which would serialise the
        # * database layer and starve a federation fan-out.
        if self._state is CircuitState.HALF_OPEN:
            log.info(
                "Circuit [%s]: HALF_OPEN -> CLOSED (probe reached the service).",
                self._name,
            )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_streak = 0
        self._release_probe()

    def _record_failure(self, exc: BaseException | None = None) -> None:
        if exc is not None and self._already_counted(exc):
            # * The same exception object travelled through a nested
            # * breaker, so it is one failure and not two. Counting it
            # * twice would trip the circuit after fewer real failures
            # * than the threshold promises.
            self._release_probe()
            return
        self._failure_count += 1
        self._success_streak = 0
        if self._state is CircuitState.HALF_OPEN:
            log.warning(
                "Circuit [%s]: HALF_OPEN -> OPEN (probe failed; retry in %.0fs).",
                self._name,
                self._recovery_timeout,
            )
            self._state = CircuitState.OPEN
            self._opened_at = monotonic()
        elif self._failure_count >= self._failure_threshold:
            log.warning(
                "Circuit [%s]: CLOSED -> OPEN (%d transient failures; retry in %.0fs).",
                self._name,
                self._failure_count,
                self._recovery_timeout,
            )
            self._state = CircuitState.OPEN
            self._opened_at = monotonic()
        self._release_probe()

    def _release_probe(self) -> None:
        self._half_open_probe_in_flight = False


# ── module-level singletons ── #

#: Circuit breaker for outbound Telegram Bot API calls (fan-out, send, etc.).
#: Trips after 5 transient timeout/network failures; recovers after 60s.
telegram: CircuitBreaker = CircuitBreaker(
    "telegram",
    failure_threshold=_DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout=_DEFAULT_RECOVERY_TIMEOUT,
)

#: Circuit breaker for PostgreSQL operations.
#: Trips after 5 transient failures; recovers after 60s.
postgres: CircuitBreaker = CircuitBreaker(
    "postgres",
    failure_threshold=_DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout=_DEFAULT_RECOVERY_TIMEOUT,
)
