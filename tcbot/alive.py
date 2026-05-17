# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import logging
import threading

from flask import Flask

from tcbot import cfg

logger = logging.getLogger(__name__)

_app = Flask(__name__)


@_app.route("/")
def index() -> str:
    """Health-check endpoint."""
    return "OK"


def _run() -> None:
    """Start Flask on the configured port."""
    _app.run(
        host="0.0.0.0",
        port=cfg.port,
        debug=False,
        use_reloader=False,
    )


def start_keepalive() -> None:
    """Launch the keep-alive server in a daemon thread."""
    t = threading.Thread(
        target=_run,
        name="keepalive",
        daemon=True,
    )
    t.start()
    logger.info("Keep-alive server started on 0.0.0.0:%d", cfg.port)
