# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Logging setup for the TCF bot.

Provides:
    - BotLogFormatter      - human-readable console format with ANSI colors
    - TelegramErrorHandler - ships every ERROR/CRITICAL log record to LOG_ERRORS
                             automatically via the running asyncio event loop
"""

from __future__ import annotations

import asyncio
import logging

from tcbot import cfg
from tcbot.utils.timedate_format import utc_now


# ────────────────────── Console Log Formatter ───────────────────── #
# * Color-coded bracket format: [HH:MM] [DD/MM/YY] [LEVEL] [module:line] → message
# * Level and message color match per severity — no background badges
# * Module name: last segment only (e.g. ban_flow, not tcbot.modules.helper.workflows.ban_flow)
# * All timestamps in UTC

class BotLogFormatter(logging.Formatter):
    """
    Custom log formatter for console output with ANSI bracket format
    * Output: [HH:MM] [DD/MM/YY] [LEVEL] [module:line] → message
    * Level text is color-coded: INFO=green, WARN=yellow, ERROR=red, CRIT=purple, DEBUG=gray
    * WARN and ERROR messages inherit their level color for instant visibility
    * Timestamps in UTC
    """

    _R  = "\033[0m"
    _BR = "\033[38;5;236m"   # bracket color — dark gray
    _TM = "\033[38;5;242m"   # time
    _DT = "\033[38;5;238m"   # date
    _MD = "\033[38;5;75m"    # module:line
    _AW = "\033[38;5;242m"   # arrow →
    _MS = "\033[38;5;253m"   # default message

    _LEVELS = {
        logging.DEBUG:    ("\033[38;5;246m", "DEBUG"),
        logging.INFO:     ("\033[38;5;114m", "INFO"),
        logging.WARNING:  ("\033[38;5;178m", "WARN"),
        logging.ERROR:    ("\033[38;5;203m", "ERROR"),
        logging.CRITICAL: ("\033[38;5;177m", "CRIT"),
    }
    _COLORED_MSG = {logging.WARNING, logging.ERROR, logging.CRITICAL}

    def __init__(self, project_name: str) -> None:
        super().__init__()
        self.project_name = project_name

    def _bracket(self, color: str, text: str) -> str:
        return f"{self._BR}[{self._R}{color}{text}{self._R}{self._BR}]{self._R}"

    def format(self, record: logging.LogRecord) -> str:
        now             = utc_now()
        level_color, level_label = self._LEVELS.get(record.levelno, ("\033[0m", "???"))
        module          = record.name.split(".")[-1]
        msg_color       = level_color if record.levelno in self._COLORED_MSG else self._MS

        time_part   = self._bracket(self._TM, now.strftime("%H:%M"))
        date_part   = self._bracket(self._DT, now.strftime("%d/%m/%y"))
        level_part  = self._bracket(level_color, level_label)
        module_part = self._bracket(self._MD, f"{module}:{record.lineno}")
        arrow_part  = f"{self._AW} → {self._R}"
        msg_part    = f"{msg_color}{record.getMessage()}{self._R}"

        return f"{time_part} {date_part} {level_part} {module_part}{arrow_part}{msg_part}"


# ─────────────────── Telegram Error Log Handler ─────────────────── #
# * Sends ERROR/CRITICAL logs to the configured LOG_ERRORS channel
# * Zero blocking — schedules coroutine on the running asyncio event loop
# * Suppression list prevents infinite loops and network noise

_SUPPRESS_PREFIXES: tuple[str, ...] = (
    "tcbot.utils.error_reporter",
    "httpcore",
    "httpx._client",
)


class TelegramErrorHandler(logging.Handler):
    """
    Async logging handler that ships errors to Telegram
    * Intercepts every ERROR/CRITICAL log record across the entire codebase
    * Schedules coroutine on running event loop — zero blocking, zero extra code
    * Skips known noise sources to prevent spam in the logs channel
    * Avoids infinite loops by suppressing its own logger's errors
    """

    def __init__(self) -> None:
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if any(record.name.startswith(p) for p in _SUPPRESS_PREFIXES):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        from tcbot.utils import error_reporter
        loop.create_task(error_reporter.report_record(record))


# ─────────────────────── Logging Setup Entry ────────────────────── #
# * Called once at bot startup — initializes all handlers and log levels

def setup(level: int = logging.INFO) -> None:
    """
    Initialize and configure the bot's logging system
    * Attaches BotLogFormatter to console handler
    * Attaches TelegramErrorHandler for ERROR/CRITICAL shipping
    * Suppresses third-party library noise on console
    * Must be called once before any logging occurs
    """
    con_handler = logging.StreamHandler()
    con_handler.setFormatter(BotLogFormatter(cfg.community_name))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(con_handler)
    root.addHandler(TelegramErrorHandler())

    for lib in ("httpx", "telegram", "motor", "pymongo"):
        logging.getLogger(lib).setLevel(logging.WARNING)