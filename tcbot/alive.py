# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""
Keep-alive server - maintains bot uptime with Flask health check endpoint
* Runs lightweight Flask server in a daemon thread to prevent platform timeouts
* Exposes a simple / endpoint that returns "OK" for health monitoring
* Uses the configured port from cfg to match the bot's main port
"""
from __future__ import annotations

import logging
import threading

from flask import Flask

from tcbot import cfg

logger = logging.getLogger(__name__)


# ───────────────────────── Flask App Setup ──────────────────────── #
# * Initialize the Flask application for health checks
_app = Flask(__name__)


@_app.route("/")
def index() -> str:
    """
    Health check endpoint that returns "OK"
    * Simple HTTP endpoint to verify the server is running
    * Used by external monitoring or platform uptime checks
    """
    return "OK"


# ──────────────────────── Server Execution ──────────────────────── #
# * Internal function to run the Flask server
# * Blocking call - must be run in a separate thread
def _run() -> None:
    """
    Start the Flask server with production-safe settings
    * Binds to 0.0.0.0 to accept connections from any interface
    * Uses the port configured in the bot's config file
    * Disables debug mode and reloader to avoid security risks
    """
    _app.run(
        host="0.0.0.0",
        port=cfg.port,
        debug=False,
        use_reloader=False,
    )


# ─────────────────────────── Public API ─────────────────────────── #
# * Entry point to start the keep-alive server from the main bot
def start_keepalive() -> None:
    """
    Launch the keep-alive server in a daemon thread
    * Creates and starts a daemon thread that runs the Flask server
    * Daemon threads automatically exit when the main program exits
    * Logs successful startup to the bot's logger
    """
    t = threading.Thread(
        target=_run,
        name="keepalive",
        daemon=True,
    )
    t.start()
    logger.info("Keep-alive server started on 0.0.0.0:%d", cfg.port)
