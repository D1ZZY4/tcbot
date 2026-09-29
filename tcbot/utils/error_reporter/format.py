# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Report formatting: secret scrubbing, tracebacks, and message building."""

from __future__ import annotations

import platform
import re
import sys
import traceback
from typing import TYPE_CHECKING, Any

from tcbot.utils.formatter import bold, code, esc, pre
from tcbot.utils.time_and_date import utc_now

from .classify import _action_hint, _classify

if TYPE_CHECKING:
    import logging

# * Telegram hard-caps a message at 4096 chars (incl. markup). Budget below
# * keeps the rendered output safely under that limit even with V2 escapes.
# * MarkdownV2 escaping uses esc() from tcbot.utils.formatter (single source).
_MAX_TB = 2200
_MAX_MSG = 250
_MAX_CTX = 250
_TB_FRAMES = 8
_MAX_LINE_CONTENT: int = 100
_REPORT_SEP_LEN: int = 30


def _shorten_path(path: str) -> str:
    """Convert raw filesystem path to a compact project-relative form."""
    p = path.replace("\\", "/")
    if "tcbot/" in p:
        return "tcbot/" + p.split("tcbot/")[-1]
    if ".venv/Lib/site-packages/" in p:
        return p.split(".venv/Lib/site-packages/")[-1]
    if ".venv/lib/python" in p:
        # *nix venv
        return p.split("site-packages/")[-1]
    return p.rsplit("/", 1)[-1]


def _condensed_tb(exc: BaseException) -> str:
    """Build a compact `file:line in func` traceback with the last few frames."""
    frames = traceback.extract_tb(exc.__traceback__)
    last = frames[-_TB_FRAMES:]
    lines: list[str] = []
    for f in last:
        path = _shorten_path(f.filename or "?")
        lines.append(f"  {path}:{f.lineno} in {f.name}")
        if f.line:
            lines.append(f"      {f.line.strip()[:_MAX_LINE_CONTENT]}")
    lines.append(f"{type(exc).__name__}: {exc}")
    out = "\n".join(lines)
    if len(out) > _MAX_TB:
        out = "...(trimmed)\n" + out[-_MAX_TB:]
    return out


def _location(
    exc: BaseException | None,
    record: logging.LogRecord | None,
) -> tuple[str, str, int]:
    """Return (file, func, line) for the report header."""
    if record is not None:
        path = _shorten_path(record.pathname)
        return path, record.funcName, record.lineno
    if exc is not None and exc.__traceback__ is not None:
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            return _shorten_path(last.filename or "?"), last.name, last.lineno or 0
    return "?", "?", 0


_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
# * The user part is optional so password-only authorities (redis://:pass@host)
# * redact too; a bare host without credentials never matches (nothing to hide).
_MONGO_AUTH_RE = re.compile(r"://(?:[^:@/\s]+)?:[^@/\s]+@")


def _pkg_cfg() -> Any:
    """Return the live package cfg so tests can monkeypatch error_reporter.cfg."""
    return sys.modules["tcbot.utils.error_reporter"].cfg


def _scrub_secrets(text: str) -> str:
    """Redact credential-shaped substrings before shipping to the log channel.

    Exact configured values are redacted first: pattern regexes cover shapes,
    but a truncated URI or token fragment could slip through, while the
    configured values themselves never belong in an error report. Mongo
    auth/network errors can echo connection strings, and any bug that
    interpolates config may leak the bot token. Redaction is pattern-based
    (bot ``id:hash`` shape, URI ``[user]:pass@`` authority with optional user,
    so ``redis://:pass@host`` is covered), so legitimate surrounding text is
    preserved.
    """
    cfg = _pkg_cfg()
    # * str.replace (not regex): URIs contain regex-significant characters,
    # * and empty values are skipped so nothing is ever blanked wholesale.
    for secret in (
        cfg.bot_token,
        cfg.mongodb_uri,
        cfg.api_hash,
        cfg.webhook_secret,
        cfg.cron_secret,
        cfg.redis_url,
    ):
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _MONGO_AUTH_RE.sub("://[REDACTED]@", text)


def scrub_text(text: str) -> str:
    """Public wrapper for secret redaction of console-bound strings."""
    return _scrub_secrets(text)


def build_error_message(
    *,
    exc: BaseException | None = None,
    record: logging.LogRecord | None = None,
    context: str | None = None,
) -> str:
    """Build a complete MarkdownV2-formatted error message for Telegram."""
    now = utc_now()
    time_str = now.strftime("%H:%M:%S UTC")
    date_str = now.strftime("%d-%m-%Y")

    if record and record.exc_info and record.exc_info[1]:
        exc = exc or record.exc_info[1]

    if record:
        raw_msg = record.getMessage()
    elif exc:
        raw_msg = str(exc)
    else:
        raw_msg = "No detail available."
    raw_msg = _scrub_secrets(raw_msg)

    file_part, func_name, line_no = _location(exc, record)
    label = _classify(exc)
    action = _action_hint(label)

    tb_block = ""
    if exc and exc.__traceback__:
        # * _condensed_tb embeds str(exc), which can echo credential-shaped
        # * substrings (bot token, Mongo URI); scrub before shipping.
        tb_block = (
            f"\n\n{bold('Traceback:')}\n{pre(_scrub_secrets(_condensed_tb(exc)))}"
        )

    ctx_block = ""
    if context:
        ctx_block = (
            f"\n\n{bold('Context:')}\n{code(_scrub_secrets(str(context))[:_MAX_CTX])}"
        )

    py_ver = sys.version.split()[0]
    host = platform.node() or "?"
    sep = "\\-" * _REPORT_SEP_LEN

    return (
        f"{bold('Error Report')}\n"
        f"{sep}\n"
        f"{bold('Type:')} {esc(label)}\n"
        f"{bold('Action:')} {esc(action)}\n"
        f"{bold('Where:')} {code(f'{file_part}:{line_no}')} in {code(func_name)}\n"
        f"{bold('When:')} {esc(time_str)} \\- {esc(date_str)}\n"
        f"{bold('Host:')} Python {esc(py_ver)} @ {esc(host)}\n"
        f"{sep}\n"
        f"{bold('Message:')}\n{code(raw_msg[:_MAX_MSG])}"
        f"{tb_block}"
        f"{ctx_block}"
    )
