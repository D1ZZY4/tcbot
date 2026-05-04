# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Logging setup for the TCF bot.

Provides:
  - BotLogFormatter  — human-readable console format
  - TelegramErrorHandler — ships every ERROR/CRITICAL log record to LOG_ERRORS
    automatically via the running asyncio event loop (no extra code needed anywhere)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from tcbot import cfg


## ── console formatter ────────────────────────────────────────────────────────

class BotLogFormatter(logging.Formatter):
    """
    [HH:MM] [DD-MM-YYYY] | <project> | <L> - <module>:<line> - <message>

    Level indicators: I=INFO, W=WARNING, E=ERROR, C=CRITICAL, D=DEBUG.
    """

    LEVEL_MAP = {
        logging.DEBUG:    "D",
        logging.INFO:     "I",
        logging.WARNING:  "W",
        logging.ERROR:    "E",
        logging.CRITICAL: "C",
    }

    def __init__(self, project_name: str):
        super().__init__()
        self.project_name = project_name

    def format(self, record: logging.LogRecord) -> str:
        now      = datetime.now(timezone.utc)
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%d-%m-%Y")
        level    = self.LEVEL_MAP.get(record.levelno, "?")
        message  = record.getMessage()
        return (
            f"[{time_str}] [{date_str}] | {self.project_name} | "
            f"{level} - {record.name}:{record.lineno} - {message}"
        )


## ── Telegram error handler ───────────────────────────────────────────────────

## Logger names whose ERROR records we intentionally suppress from Telegram
## (they are usually network noise, not actionable bugs).
_SUPPRESS_PREFIXES = (
    "tcbot.utils.error_reporter",   # avoid infinite loop
    "httpcore",
    "httpx._client",
)


class TelegramErrorHandler(logging.Handler):
    """Intercepts every ERROR/CRITICAL log record across the entire codebase
    and ships it to the LOG_ERRORS Telegram channel asynchronously.

    Works by scheduling a coroutine on the running asyncio event loop inside
    emit() — zero blocking, zero per-module code required.
    """

    def __init__(self) -> None:
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        ## Guard: skip records from our own reporter (no infinite loop)
        if any(record.name.startswith(p) for p in _SUPPRESS_PREFIXES):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  ## no running event loop — startup or teardown, skip

        ## Import lazily to avoid circular imports at module load time
        from tcbot.utils import error_reporter
        loop.create_task(error_reporter.report_record(record))


## ── setup ────────────────────────────────────────────────────────────────────

def setup(level: int = logging.INFO) -> None:
    formatter    = BotLogFormatter(cfg.community_name)
    con_handler  = logging.StreamHandler()
    con_handler.setFormatter(formatter)

    tg_handler   = TelegramErrorHandler()

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(con_handler)
    root.addHandler(tg_handler)

    ## Reduce noise from third-party libraries on the console;
    ## TelegramErrorHandler still fires for their ERRORs if important.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
