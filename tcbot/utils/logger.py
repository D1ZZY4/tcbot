# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Logging setup for the TCF bot."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

import structlog
from structlog.typing import EventDict, FilteringBoundLogger

from tcbot.utils.time_and_date import from_timestamp

# ────────────────────── Console Log Formatter ───────────────────── #
# * Color-coded bracket format: [HH:MM] [DD/MM/YY] [LEVEL] [module:line] → message
# * Level and message color match per severity; no background badges
# * Module name: last segment only (e.g. ban_flow, not tcbot.modules.helper.workflows.ban_flow)
# * All timestamps in UTC


class BotLogFormatter(logging.Formatter):
    """Custom log formatter for console output with ANSI bracket format."""

    _R = "\033[0m"
    _BR = "\033[38;5;236m"  # bracket color (dark gray)
    _TM = "\033[38;5;242m"  # time
    _DT = "\033[38;5;238m"  # date
    _MD = "\033[38;5;75m"  # module:line
    _AW = "\033[38;5;242m"  # arrow →
    _MS = "\033[38;5;253m"  # default message

    _LEVELS: ClassVar[dict[int, tuple[str, str]]] = {
        logging.DEBUG: ("\033[38;5;246m", "DEBUG"),
        logging.INFO: ("\033[38;5;114m", "INFO"),
        logging.WARNING: ("\033[38;5;178m", "WARN"),
        logging.ERROR: ("\033[38;5;203m", "ERROR"),
        logging.CRITICAL: ("\033[38;5;177m", "CRIT"),
    }
    _COLORED_MSG: ClassVar[set[int]] = {
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    }

    def _bracket(self, color: str, text: str) -> str:
        """Wrap *text* in ANSI-coloured square brackets using the given *color* code."""
        return f"{self._BR}[{self._R}{color}{text}{self._R}{self._BR}]{self._R}"

    def _context_segment(self) -> str:
        """Colored request-context segment from structlog contextvars, or "" when absent."""
        ctx = structlog.contextvars.get_contextvars()
        parts: list[str] = []
        if ctx.get("user_id") is not None:
            parts.append(f"u={ctx['user_id']}")
        if ctx.get("chat_id") is not None:
            parts.append(f"c={ctx['chat_id']}")
        if ctx.get("update_id") is not None:
            parts.append(f"#{ctx['update_id']}")
        if not parts:
            return ""
        return f" {self._BR}[{self._R}{self._MD}{' '.join(parts)}{self._R}{self._BR}]{self._R}"

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with ANSI-colored time, date, level, module, and message.

        Appends formatted exception and stack-info blocks when present so that
        ``log.exception()`` and ``exc_info=True`` calls produce fully colored output.
        """
        # * Use the record's creation time, not now: buffered or delayed
        # * formatting would otherwise misorder events.
        now = from_timestamp(record.created)
        level_color, level_label = self._LEVELS.get(record.levelno, ("\033[0m", "???"))
        module = record.name.split(".")[-1]
        msg_color = level_color if record.levelno in self._COLORED_MSG else self._MS

        time_part = self._bracket(self._TM, now.strftime("%H:%M"))
        date_part = self._bracket(self._DT, now.strftime("%d/%m/%y"))
        level_part = self._bracket(level_color, level_label)
        module_part = self._bracket(self._MD, f"{module}:{record.lineno}")
        arrow_part = f"{self._AW} → {self._R}"
        msg_part = f"{msg_color}{record.getMessage()}{self._R}"

        output = (
            f"{time_part} {date_part} {level_part} {module_part}"
            f"{self._context_segment()}{arrow_part}{msg_part}"
        )

        # * Append traceback for log.exception() and explicit exc_info=... calls.
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                output += f"\n{level_color}{record.exc_text}{self._R}"
        if record.stack_info:
            output += f"\n{level_color}{self.formatStack(record.stack_info)}{self._R}"
        return output


# ─────────────────── Telegram Error Log Handler ─────────────────── #
# * Sends ERROR/CRITICAL logs to the configured LOG_ERRORS channel
# * Zero blocking; schedules coroutine on the running asyncio event loop
# * Suppression list prevents infinite loops and network noise

# * Strong references to in-flight Telegram error report tasks (prevents GC)
_tg_tasks: set[asyncio.Task[None]] = set()


async def drain_pending() -> None:
    """Await in-flight Telegram log-shipping tasks at shutdown (bounded)."""
    from tcbot.utils.dispatch import (  # noqa: PLC0415 (keeps logger import-light)
        drain_tasks,
    )

    await drain_tasks(_tg_tasks, label="log shipping")


_SUPPRESS_PREFIXES: tuple[str, ...] = (
    "tcbot.utils.error_reporter",
    "httpcore",
    "httpx._client",
)


class TelegramErrorHandler(logging.Handler):
    """Async logging handler that ships errors to Telegram."""

    def __init__(self) -> None:
        """Register the handler at ERROR level."""
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        """Schedule an async Telegram error report for the given log record."""
        if any(record.name.startswith(p) for p in _SUPPRESS_PREFIXES):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.handleError(record)
            return
        try:
            from tcbot.utils import (  # noqa: PLC0415
                error_reporter,
            )
        except ImportError:
            self.handleError(record)
            return

        task = loop.create_task(error_reporter.report_record(record))
        _tg_tasks.add(task)
        task.add_done_callback(_tg_tasks.discard)


# ─────────────────────── Logging Setup Entry ────────────────────── #
# * Called once at bot startup; initializes all handlers and log levels


def _structlog_setup() -> None:
    """Configure structlog to output through stdlib logging."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            _render_event_string,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # * Never cache: tcbot.modules logs once at import time, before
        # * setup() runs. A cached pre-setup proxy would print to stdout
        # * forever instead of reaching the handlers installed here.
        cache_logger_on_first_use=False,
    )


def _render_event_string(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> str:
    """Reduce the event mapping to its message string (final structlog processor).

    Our handlers render through BotLogFormatter (a plain logging.Formatter),
    not ProcessorFormatter, and wrap_for_formatter only packs whatever it
    receives: without this step record.msg would be the raw mapping and every
    line would print as a dict. Context, timestamps, and tracebacks render
    from contextvars and the record itself in BotLogFormatter, so only the
    event text crosses here. Tracebacks still land once via record.exc_info
    (stdlib exception() sets it; the only explicit exc_info call site stays
    on stdlib in __main__).
    """
    return str(event_dict.get("event", ""))


def setup(level: int = logging.INFO) -> None:
    """Initialize and configure the bot's logging system."""
    _structlog_setup()

    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, BotLogFormatter
        ):
            break
    else:
        con_handler = logging.StreamHandler()
        con_handler.setFormatter(BotLogFormatter())
        root.addHandler(con_handler)

    if not any(isinstance(handler, TelegramErrorHandler) for handler in root.handlers):
        root.addHandler(TelegramErrorHandler())

    for lib in ("httpx", "telegram", "motor", "pymongo"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ─────────────────── Public structlog API ───────────────────── #
# * Single owner for logger creation and request correlation. Modules
# * call get_logger(__name__) instead of logging.getLogger: records flow
# * through the same stdlib handlers above, so every line keeps the
# * colored bracket format, Telegram shipping, and level discipline.
# * Import-time loggers (tcbot/__init__, tcbot/modules/__init__) stay on
# * stdlib: they emit before setup() installs these handlers.


def get_logger(name: str) -> FilteringBoundLogger:
    """Return the structlog logger for *name* (stdlib-backed, colored output)."""
    return structlog.get_logger(name)


def bind_request_context(
    *,
    update_id: int | str | None = None,
    user_id: int | None = None,
    chat_id: int | None = None,
) -> None:
    """Bind per-update tracing context rendered on every log line until cleared.

    log_execution binds on handler entry and clears in a finally block, so
    concurrent updates never leak context into each other (contextvars are
    task-local). BotLogFormatter reads the bound values directly, which also
    covers plain stdlib records from third-party libraries.
    """
    ctx: dict[str, object] = {}
    if update_id is not None:
        ctx["update_id"] = update_id
    if user_id is not None:
        ctx["user_id"] = user_id
    if chat_id is not None:
        ctx["chat_id"] = chat_id
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def clear_request_context() -> None:
    """Drop all bound request context (see bind_request_context)."""
    structlog.contextvars.clear_contextvars()
