# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Keep-alive server - maintains bot uptime with Flask health check endpoint."""

from __future__ import annotations

import logging
import threading

from flask import Flask

from tcbot import cfg

log = logging.getLogger(__name__)


# ───────────────────────── Flask App Setup ──────────────────────── #
# * Initialize the Flask application for health checks
_app = Flask(__name__)


@_app.route("/")
def index() -> str:
    """Health check endpoint that returns "OK"."""
    return "OK"


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
