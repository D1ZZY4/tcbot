# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Logging setup for the TCF bot (Loguru backend)."""

from __future__ import annotations

import copy
import logging
import threading
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

# * Loguru owns the level registry. Integrations that need a numeric level
# * read it from here instead of importing the standard logging module.
ERROR_LEVEL: int = logger.level("ERROR").no

# ────────────────────── Request context ─────────────────────────────── #

_ctx: ContextVar[tuple[int | str | None, int | None, int | None] | None] = ContextVar(
    "tcbot_log_ctx", default=None
)

_last_minute_bucket: int | None = None
_last_time_parts: tuple[str, str] = ("--:--", "--/--/--")


def _context_segment() -> str:
    ctx = _ctx.get()
    if ctx is None:
        return ""
    update_id, user_id, chat_id = ctx
    parts: list[str] = []
    if user_id is not None:
        parts.append(f"u={user_id}")
    if chat_id is not None:
        parts.append(f"c={chat_id}")
    if update_id is not None:
        parts.append(f"#{update_id}")
    return f" [{' '.join(parts)}]" if parts else ""


def _safe_time_parts(created: float) -> tuple[str, str]:
    """Return ``(HH:MM, DD/MM/YY)`` in UTC, or placeholders when conversion fails.

    Formatter runs on the logging path, including during interpreter
    shutdown when modules are torn down: a conversion failure must never
    turn a log line into a "Logging error" traceback.
    """
    global _last_minute_bucket, _last_time_parts
    try:
        bucket = int(created) // 60
        if bucket == _last_minute_bucket:
            return _last_time_parts
        now = datetime.fromtimestamp(created, tz=UTC)
    except ImportError, OSError, OverflowError, ValueError:
        return "--:--", "--/--/--"
    parts = (
        f"{now.hour:02d}:{now.minute:02d}",
        f"{now.day:02d}/{now.month:02d}/{now.year % 100:02d}",
    )
    _last_minute_bucket = bucket
    _last_time_parts = parts
    return parts


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
    _ARROW_PART: ClassVar[str] = f"{_AW} → {_R}"
    _LEVEL_PARTS: ClassVar[dict[int, str]] = {}
    _DEFAULT_LEVEL_PART: ClassVar[str] = f"{_BR}[{_R}{_R}???{_R}{_BR}]{_R}"

    def _bracket(self, color: str, text: str) -> str:
        return f"{self._BR}[{self._R}{color}{text}{self._R}{self._BR}]{self._R}"

    def format(self, record: logging.LogRecord) -> str:
        """Format a record with ANSI time, date, level, module, and message."""
        hhmm, ddmmyy = _safe_time_parts(record.created)
        level_color, _ = self._LEVELS.get(record.levelno, ("\033[0m", "???"))
        module = record.name.rsplit(".", 1)[-1]
        msg_color = level_color if record.levelno in self._COLORED_MSG else self._MS
        time_part = self._bracket(self._TM, hhmm)
        date_part = self._bracket(self._DT, ddmmyy)
        level_part = self._LEVEL_PARTS.get(record.levelno, self._DEFAULT_LEVEL_PART)
        module_part = self._bracket(self._MD, f"{module}:{record.lineno}")
        try:
            message_text = record.getMessage()
        except TypeError, ValueError:
            message_text = str(record.msg) if record.msg is not None else ""
        output = (
            f"{time_part} {date_part} {level_part} {module_part}"
            f"{_context_segment()}{self._ARROW_PART}{msg_color}{message_text}{self._R}"
        )
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                output += f"\n{level_color}{record.exc_text}{self._R}"
        if record.stack_info:
            output += f"\n{level_color}{self.formatStack(record.stack_info)}{self._R}"
        return output


BotLogFormatter._LEVEL_PARTS = {
    lvl: f"{BotLogFormatter._BR}[{BotLogFormatter._R}{color}{label}{BotLogFormatter._R}{BotLogFormatter._BR}]{BotLogFormatter._R}"
    for lvl, (color, label) in BotLogFormatter._LEVELS.items()
}


# ─────────────────── Telegram Error Log Handler ─────────────────── #

_SUPPRESS_PREFIXES: tuple[str, ...] = (
    "tcbot.error_reporter",
    "httpcore",
    "httpx._client",
)

# * Registered by the error reporter at startup. The reporter lives above
# * the utils layer, so the logger must not import it: a direct import
# * would close a cycle between the two. Registering the sink keeps the
# * dependency one-way.
_record_sink: Callable[[logging.LogRecord], None] | None = None

# * Loguru handlers hold a non-reentrant thread-local lock while a sink runs.
# * The bridge calls stdlib handlers inside that sink, so any project log call
# * on this thread must go to stdlib: re-entering Loguru becomes a swallowed
# * "Logging error in Loguru Handler" dump instead of an operator-visible line.
_in_sink = threading.local()


def set_record_sink(sink: Callable[[logging.LogRecord], None] | None) -> None:
    """Register the callable that ships a log record to the error channel.

    The callable is invoked synchronously from the logging handler and is
    responsible for scheduling the delivery itself; the logger only
    forwards the record. That keeps the delivery lifecycle with the owner
    of the delivery instead of with the formatter. Pass ``None`` to stop
    shipping. Without a registered sink the logger still writes the record
    to the console; only the Telegram delivery is skipped.
    """
    global _record_sink
    _record_sink = sink


class TelegramErrorHandler(logging.Handler):
    """Stdlib handler that ships errors to Telegram (via Loguru bridge)."""

    def __init__(self) -> None:
        """Initialize the handler at ERROR level."""
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        """Forward the record to the registered sink."""
        if any(record.name.startswith(p) for p in _SUPPRESS_PREFIXES):
            return
        sink = _record_sink
        if sink is None:
            return
        try:
            # * Snapshot now: _bridge_to_stdlib clears exc_info on the live
            # * record after callHandlers, which would otherwise erase the
            # * traceback before the delivery reads it.
            sink(copy.copy(record))
        except Exception as exc:
            # * This runs inside Loguru's non-reentrant sink. Stdlib keeps the
            # * outage visible on the console without re-entering Loguru, and
            # * the WARNING stays below this ERROR-level handler.
            logging.getLogger(__name__).warning("Error log sink failed: %s", exc)


# ─────────────────────── Logging Setup ──────────────────────────── #


_LOGURU_LEVEL_MAP: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _bridge_to_stdlib(message: Any) -> None:
    """Forward a Loguru message to stdlib so caplog and shipping keep working."""
    record = message.record
    level = _LOGURU_LEVEL_MAP.get(record["level"].name, 20)
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
        func=record["function"] or "",
    )
    if std_record.exc_info:
        std_record.exc_text = None
    _in_sink.active = True
    try:
        std_logger.callHandlers(std_record)
    finally:
        _in_sink.active = False
        std_record.exc_info = None


def setup(level: int = logging.INFO) -> None:
    """Initialize and configure the bot logging system (Loguru).

    Loguru owns the API and the stdlib handlers own the output: every
    record is bridged once and rendered by ``BotLogFormatter``. A second
    Loguru console sink would print the same record twice.
    """
    logger.remove()
    # * The bridge stays at DEBUG so caplog can lower the level of one
    # * logger; ``_bridge_to_stdlib`` applies the stdlib level discipline
    # * before the record reaches any handler.
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
    for lib in ("httpx", "telegram", "sqlalchemy", "apscheduler"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ─────────────────── Public Loguru API ────────────────────────── #


_LEVEL_NO: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


class _LoguruShim:
    """Compat shim so existing %-style call sites log through Loguru."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._std_logger = logging.getLogger(name)

    def is_debug_enabled(self) -> bool:
        """Return True when DEBUG level is enabled for this logger."""
        return self._std_logger.isEnabledFor(logging.DEBUG)

    def _emit_checked(
        self, level: str, msg: str, args: tuple[Any, ...], exc_info: Any = None
    ) -> None:
        text = _format_percent(msg, args)
        if getattr(_in_sink, "active", False):
            # * The Loguru sink already holds a non-reentrant handler lock.
            # * Stdlib delivers this line to the same console without trying
            # * to acquire that lock again.
            getattr(self._std_logger, level)(text, exc_info=exc_info)
            return
        bound = logger.bind(module=self._name)
        if exc_info:
            getattr(bound.opt(depth=2, exception=exc_info), level)(text)
        else:
            getattr(bound.opt(depth=2), level)(text)

    def _emit(
        self, level: str, msg: str, args: tuple[Any, ...], exc_info: Any = None
    ) -> None:
        if not self._std_logger.isEnabledFor(_LEVEL_NO.get(level, logging.INFO)):
            return
        self._emit_checked(level, msg, args, exc_info=exc_info)

    def debug(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        if self._std_logger.isEnabledFor(logging.DEBUG):
            self._emit_checked("debug", msg, args, exc_info=exc_info)

    def info(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        if self._std_logger.isEnabledFor(logging.INFO):
            self._emit_checked("info", msg, args, exc_info=exc_info)

    def warning(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        if self._std_logger.isEnabledFor(logging.WARNING):
            self._emit_checked("warning", msg, args, exc_info=exc_info)

    def error(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        if self._std_logger.isEnabledFor(logging.ERROR):
            self._emit_checked("error", msg, args, exc_info=exc_info)

    def critical(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        if self._std_logger.isEnabledFor(logging.CRITICAL):
            self._emit_checked("critical", msg, args, exc_info=exc_info)

    def exception(self, msg: str, *args: Any, exc_info: Any = None) -> None:
        """Log at error level with the handled exception attached.

        ``exc_info`` follows the stdlib contract: it defaults to ``True``
        (attach the exception currently being handled) and ``False``
        suppresses the traceback.
        """
        if self._std_logger.isEnabledFor(logging.ERROR):
            self._emit_checked(
                "error", msg, args, exc_info=True if exc_info is None else exc_info
            )


def get_logger(name: str) -> _LoguruShim:
    """Return the Loguru-backed logger for *name*."""
    return _LoguruShim(name)


def bind_request_context(
    *,
    update_id: int | str | None = None,
    user_id: int | None = None,
    chat_id: int | None = None,
) -> None:
    """Bind per-ctx tracing context rendered on every log line until cleared."""
    if update_id is not None or user_id is not None or chat_id is not None:
        _ctx.set((update_id, user_id, chat_id))


def clear_request_context() -> None:
    """Drop all bound request context."""
    _ctx.set(None)
