# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Keep-alive server: Flask health check and metrics endpoint.

The bot receives updates through Kurigram's native long polling, so this
server only serves independent operational endpoints (uptime, health and
optional Prometheus metrics). It never accepts Telegram updates.
"""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

import msgspec
from flask import Flask

from tcbot import cfg
from tcbot.database import engine as db_engine
from tcbot.database import redis_client
from tcbot.database import scheduler as sched_mod
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.circuit_breaker import CircuitState
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)


# ───────────────────────── Flask App Setup ──────────────────────── #
_app = Flask(__name__)

# * Set by the polling lifecycle around idle(). A keep-alive thread can keep
# * answering while the client has already stopped consuming updates, so the
# * health verdict needs a direct signal instead of inferring liveness from
# * the database and the circuit breakers.
_polling_active: bool = False


def set_polling_active(*, active: bool) -> None:
    """Record whether the Kurigram polling loop is currently running."""
    global _polling_active
    _polling_active = active


# ──────────────────── Optional Prometheus metrics ───────────────── #
# * prometheus-client is optional (the observability extra); the endpoint
# * registers only when the package is installed. Default process metrics
# * (CPU/RAM/fds) expose what Prometheus scrapes; bot health stays on
# * /health.
try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore[reportMissingImports]

    _METRICS_RESPONSE: tuple[Callable[[], bytes], str] | None = (
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
except ImportError:
    _METRICS_RESPONSE = None

if _METRICS_RESPONSE is not None:
    _generate_latest, _metrics_content_type = _METRICS_RESPONSE

    @_app.route("/metrics")
    def metrics() -> tuple[bytes, int, dict[str, str]]:
        """Expose Prometheus metrics (observability extra only)."""
        return _generate_latest(), 200, {"Content-Type": _metrics_content_type}


@_app.route("/")
def index() -> str:
    """Keep-alive endpoint that returns OK for basic uptime monitoring."""
    return "OK"


class _HealthPayload(msgspec.Struct):
    """Typed /health body: fixed string fields in a stable key order."""

    status: str
    database: str
    redis: str
    scheduler: str
    circuit_telegram: str
    circuit_database: str
    polling: str
    ts: str


@_app.route("/health")
def health() -> tuple[str, int, dict[str, str]]:
    """Detailed health status as JSON: database, redis, scheduler, timestamp.

    Returns HTTP 200 when all core subsystems are ready, 503 when degraded.
    The database and scheduler state reflect the last-known connection status
    established during startup; no live pings are issued (those require async).
    """
    database_ok = db_engine.is_connected()
    scheduler_ok = sched_mod.is_ready()

    # * is_connected() is a sticky startup flag (never cleared on partition),
    # * so AND it with the live circuit state: after 5 consecutive DB failures
    # * the database breaker opens and the field must read error, matching the
    # * overall verdict below.
    db_state = _cb.postgres.peek_state()
    # * Circuit must be fully CLOSED for the DB to count healthy: HALF_OPEN
    # * (recovery probe pending or timed out) is a degraded state, and OPEN
    # * is a hard failure. peek_state() reads without transitioning, so an
    # * uptime poll cannot silently move OPEN -> HALF_OPEN.
    if db_state is not CircuitState.CLOSED:
        database_ok = False

    if not cfg.redis_url:
        redis_status = "disabled"
    else:
        redis_liveness = redis_client.liveness()
        redis_status = (
            "ok"
            if redis_liveness is True
            else "error"
            if redis_liveness is False
            else "unknown"
        )

    tg_state = _cb.telegram.peek_state()
    polling_ok = _polling_active

    # * Both circuits must be fully CLOSED for their subsystem to count
    # * healthy: HALF_OPEN (recovery probe pending or timed out) is degraded
    # * on either side, and OPEN is a hard failure. Redis stays a hint-only
    # * field by design: the bot serves fully from the in-memory layer when
    # * Redis is down, so a Redis outage must not page the instance.
    overall = (
        "ok"
        if (
            database_ok
            and scheduler_ok
            and polling_ok
            and tg_state is CircuitState.CLOSED
            and db_state is CircuitState.CLOSED
        )
        else "degraded"
    )
    payload = _HealthPayload(
        status=overall,
        database="ok" if database_ok else "error",
        redis=redis_status,
        scheduler="ok" if scheduler_ok else "error",
        circuit_telegram=tg_state.value,
        circuit_database=db_state.value,
        polling="ok" if polling_ok else "error",
        ts=utc_now().isoformat(timespec="seconds"),
    )
    code = 200 if overall == "ok" else 503
    return (
        msgspec.json.encode(payload).decode("utf-8"),
        code,
        {"Content-Type": "application/json"},
    )


# ──────────────────────── Server Execution ──────────────────────── #
# * Blocking call: must run in a separate thread, never on the event loop.
def _run() -> None:
    """Start the Flask server with production-safe settings."""
    _app.run(
        host=cfg.bind_host,
        port=cfg.port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# ─────────────────────────── Public API ─────────────────────────── #
def start_keepalive() -> None:
    """Launch the Flask server in a daemon thread.

    Probes the port first: a bind failure inside the daemon thread would
    only surface as a thread traceback while the bot runs on headless
    (no health checks). Fail fast at startup instead.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # * Werkzeug binds with SO_REUSEADDR. Without it the probe fails on a
        # * port left in TIME_WAIT by a restart even though the real bind
        # * would have succeeded, aborting bot startup for no real conflict.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((cfg.bind_host, cfg.port))
    except OSError as exc:
        raise RuntimeError(f"Keep-alive port {cfg.port} is unavailable: {exc}") from exc
    finally:
        probe.close()
    t = threading.Thread(
        target=_run,
        name="keepalive",
        daemon=True,
    )
    t.start()
    log.info("Keep-alive server started on %s:%d", cfg.bind_host, cfg.port)
