# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Logging setup for the TCF bot (Loguru backend)."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, ClassVar

from loguru import logger

# ────────────────────── Request context ─────────────────────────────── #

_ctx: ContextVar[dict[str, object] | None] = ContextVar("tcbot_log_ctx", default=None)


def _context_segment() -> str:
    ctx = _ctx.get() or {}
    parts: list[str] = []
    if ctx.get("user_id") is not None:
        parts.append(f"u={ctx['user_id']}")
    if ctx.get("chat_id") is not None:
        parts.append(f"c={ctx['chat_id']}")
    if ctx.get("update_id") is not None:
        parts.append(f"#{ctx['update_id']}")
    return f" [{' '.join(parts)}]" if parts else ""


def _safe_time_parts(created: float) -> tuple[str, str]:
    """Return ``(HH:MM, DD/MM/YY)`` in UTC, or placeholders when conversion fails.

    Formatter runs on the logging path, including during interpreter
    shutdown when modules are torn down: a conversion failure must never
    turn a log line into a "Logging error" traceback.
    """
    try:
        now = datetime.fromtimestamp(created, tz=UTC)
    except ImportError, OSError, OverflowError, ValueError:
        return "--:--", "--/--/--"
    return now.strftime("%H:%M"), now.strftime("%d/%m/%y")


def _format_percent(msg: str, args: tuple[Any, ...]) -> str:
    """Interpolate ``msg % args`` without ever raising into the caller.

    The shim eagerly formats %-style call sites; a mismatched format
    string (literal ``%`` without args, wrong count) must degrade to the
    raw message plus args instead of crashing the handler that logged it.
    """
    if not args:
        return msg
    try:
        return msg % args
    except TypeError, ValueError:
        try:
            return f"{msg} (args={args!r})"
        except Exception:
            return msg


# ────────────────────── Console Log Formatter ───────────────────── #

# * Color-coded bracket format: [HH:MM] [DD/MM/YY] [LEVEL] [module:line] → message
# * Module name: last segment only; all timestamps in UTC.


class BotLogFormatter(logging.Formatter):
    """Custom stdlib formatter for console output with ANSI bracket format."""

    _R = "\033[0m"
    _BR = "\033[38;5;236m"
    _TM = "\033[38;5;242m"
    _DT = "\033[38;5;238m"
    _MD = "\033[38;5;75m"
    _AW = "\033[38;5;242m"
    _MS = "\033[38;5;253m"

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
        return f"{self._BR}[{self._R}{color}{text}{self._R}{self._BR}]{self._R}"

    def format(self, record: logging.LogRecord) -> str:
        """Format a record with ANSI time, date, level, module, and message."""
        hhmm, ddmmyy = _safe_time_parts(record.created)
        level_color, level_label = self._LEVELS.get(record.levelno, ("\033[0m", "???"))
        module = record.name.split(".")[-1]
        msg_color = level_color if record.levelno in self._COLORED_MSG else self._MS
        time_part = self._bracket(self._TM, hhmm)
        date_part = self._bracket(self._DT, ddmmyy)
        level_part = self._bracket(level_color, level_label)
        module_part = self._bracket(self._MD, f"{module}:{record.lineno}")
        arrow_part = f"{self._AW} → {self._R}"
        try:
            message_text = record.getMessage()
        except TypeError, ValueError:
            message_text = str(record.msg) if record.msg is not None else ""
        msg_part = f"{msg_color}{message_text}{self._R}"
        output = (
            f"{time_part} {date_part} {level_part} {module_part}"
            f"{_context_segment()}{arrow_part}{msg_part}"
        )
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                output += f"\n{level_color}{record.exc_text}{self._R}"
        if record.stack_info:
            output += f"\n{level_color}{self.formatStack(record.stack_info)}{self._R}"
        return output


# ─────────────────── Telegram Error Log Handler ─────────────────── #

_tg_tasks: set[asyncio.Task[None]] = set()


async def drain_pending() -> None:
    """Await in-flight Telegram log-shipping tasks at shutdown (bounded)."""
    from tcbot.utils.dispatch import drain_tasks  # noqa: PLC0415

    await drain_tasks(_tg_tasks, label="log shipping")


_SUPPRESS_PREFIXES: tuple[str, ...] = (
    "tcbot.utils.error_reporter",
    "httpcore",
    "httpx._client",
)


class TelegramErrorHandler(logging.Handler):
    """Stdlib handler that ships errors to Telegram (via Loguru bridge)."""

    def __init__(self) -> None:
        """Initialize the handler at ERROR level."""
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        """Schedule an async Telegram error report for the record."""
        if any(record.name.startswith(p) for p in _SUPPRESS_PREFIXES):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.handleError(record)
            return
        try:
            from tcbot.utils import error_reporter  # noqa: PLC0415
        except ImportError:
            self.handleError(record)
            return
        task = loop.create_task(error_reporter.report_record(record))
        _tg_tasks.add(task)
        task.add_done_callback(_tg_tasks.discard)


# ─────────────────────── Logging Setup ──────────────────────────── #


def _bridge_to_stdlib(message: Any) -> None:
    """Forward a Loguru message to stdlib so caplog and shipping keep working."""
    record = message.record
    level = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(
        record["level"].name, 20
    )
    exc = record["exception"]
    log_name: str = record["name"] or record["extra"].get("module") or "tcbot"
    std_logger = logging.getLogger(log_name)
    # * Stdlib level discipline applies here: a DEBUG line bridges only
    # * when its logger is enabled for DEBUG, so production at INFO stays
    # * quiet while caplog at DEBUG still captures diagnostics.
    if not std_logger.isEnabledFor(level):
        return
    pathname = record["file"].path if record["file"] else ""
    std_record = std_logger.makeRecord(
        log_name,
        level,
        pathname,
        record["line"],
        record["message"],
        (),
        (exc.type, exc.value, exc.traceback) if exc and exc.value is not None else None,
    )
    if std_record.exc_info:
        std_record.exc_text = None
    std_logger.callHandlers(std_record)
    std_record.exc_info = None


def setup(level: int = logging.INFO) -> None:
    """Initialize and configure the bot logging system (Loguru)."""
    logger.remove()
    level_name = logging.getLevelName(level)
    logger.add(
        lambda m: print(_render_loguru(m)),
        level=level_name,
        colorize=True,
    )
    logger.add(_bridge_to_stdlib, level="DEBUG")
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


def _render_loguru(message: Any) -> str:
    record = message.record
    hhmm, ddmmyy = _safe_time_parts(record["time"].timestamp())
    level_map = {
        "DEBUG": ("\033[38;5;246m", "DEBUG"),
        "INFO": ("\033[38;5;114m", "INFO"),
        "WARNING": ("\033[38;5;178m", "WARN"),
        "ERROR": ("\033[38;5;203m", "ERROR"),
        "CRITICAL": ("\033[38;5;177m", "CRIT"),
    }
    color, label = level_map.get(record["level"].name, ("\033[0m", "???"))
    raw_name = record["name"] or record["extra"].get("module", "?")
    module = raw_name.split(".")[-1]
    return (
        f"[<f2>{hhmm}</f2>] [<f2>{ddmmyy}</f2>] "
        f"[<{color}>{label}</>] [<f4>{module}:{record['line']}</>]"
        f"{_context_segment()} <f2>→</f2> {record['message']}"
    )


# ─────────────────── Public Loguru API ────────────────────────── #


class _LoguruShim:
    """Compat shim so existing %-style call sites log through Loguru."""

    def __init__(self, name: str) -> None:
        self._name = name

    def _emit(
        self, level: str, msg: str, args: tuple[Any, ...], exc_info: Any = None
    ) -> None:
        text = _format_percent(msg, args)
        bound = logger.bind(module=self._name)
        if exc_info:
            bound.opt(depth=2, exception=exc_info).error(text)
        else:
            getattr(bound.opt(depth=2), level)(text)

    def debug(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        self._emit("debug", msg, args, exc_info=exc_info)

    def info(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        self._emit("info", msg, args, exc_info=exc_info)

    def warning(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        self._emit("warning", msg, args, exc_info=exc_info)

    def error(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        self._emit("error", msg, args, exc_info=exc_info)

    def critical(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        self._emit("critical", msg, args, exc_info=exc_info)

    def exception(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        text = _format_percent(msg, args)
        logger.bind(module=self._name).opt(depth=2, exception=True).error(text)


def get_logger(name: str) -> _LoguruShim:
    """Return the Loguru-backed logger for *name*."""
    return _LoguruShim(name)


def bind_request_context(
    *,
    update_id: int | str | None = None,
    user_id: int | None = None,
    chat_id: int | None = None,
) -> None:
    """Bind per-update tracing context rendered on every log line until cleared."""
    ctx: dict[str, object] = {}
    if update_id is not None:
        ctx["update_id"] = update_id
    if user_id is not None:
        ctx["user_id"] = user_id
    if chat_id is not None:
        ctx["chat_id"] = chat_id
    if ctx:
        _ctx.set(ctx)


def clear_request_context() -> None:
    """Drop all bound request context."""
    _ctx.set(None)
