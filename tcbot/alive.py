# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Keep-alive server - maintains bot uptime with Flask health check endpoint."""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime

from flask import Flask

from tcbot import cfg
from tcbot.database import mongos, redis_client
from tcbot.database import scheduler as sched_mod

log = logging.getLogger(__name__)


# ───────────────────────── Flask App Setup ──────────────────────── #
# * Initialize the Flask application for health checks
_app = Flask(__name__)


@_app.route("/")
def index() -> str:
    """Keep-alive endpoint that returns "OK" for basic uptime monitoring."""
    return "OK"


@_app.route("/health")
def health() -> tuple[str, int, dict[str, str]]:
    """Detailed health status as JSON: mongodb, redis, scheduler, and timestamp.

    Returns HTTP 200 when all core subsystems are ready, 503 when degraded.
    Note: mongodb and scheduler state reflect the last-known connection status
    established during startup; no live pings are issued (those require async).
    """
    mongodb_ok = mongos.is_connected()
    scheduler_ok = sched_mod.is_ready()

    rc = redis_client.client()
    if rc is not None:
        redis_status = "ok"
    elif cfg.redis_url:
        redis_status = "error"
    else:
        redis_status = "disabled"

    overall = "ok" if (mongodb_ok and scheduler_ok) else "degraded"
    payload = {
        "status": overall,
        "mongodb": "ok" if mongodb_ok else "error",
        "redis": redis_status,
        "scheduler": "ok" if scheduler_ok else "error",
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    code = 200 if overall == "ok" else 503
    return json.dumps(payload), code, {"Content-Type": "application/json"}


# ──────────────────────── Server Execution ──────────────────────── #
# * Internal function to run the Flask server
# * Blocking call - must be run in a separate thread
def _run() -> None:
    """Start the Flask server with production-safe settings."""
    _app.run(
        host="0.0.0.0",
        port=cfg.port,
        debug=False,
        use_reloader=False,
    )


# ─────────────────────────── Public API ─────────────────────────── #
# * Entry point to start the keep-alive server from the main bot
def start_keepalive() -> None:
    """Launch the keep-alive server in a daemon thread."""
    t = threading.Thread(
        target=_run,
        name="keepalive",
        daemon=True,
    )
    t.start()
    log.info("Keep-alive server started on 0.0.0.0:%d", cfg.port)
