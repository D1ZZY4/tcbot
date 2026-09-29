# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralized error reporter: classifies, formats, dedupes, and ships errors to LOG_ERRORS."""

from __future__ import annotations

from typing import Any

from tcbot import cfg

from . import ship as _ship
from . import state as _state
from .classify import (
    _ACTION_HINTS,
    _BENIGN_PATTERNS,
    _LOG_NOISE_PATTERNS,
    _OWNER_ONLY_TYPES,
    _action_hint,
    _benign,
    _classify,
    _log_noise,
    _owner_only,
)
from .format import (
    _MAX_CTX,
    _MAX_LINE_CONTENT,
    _MAX_MSG,
    _MAX_TB,
    _MONGO_AUTH_RE,
    _REPORT_SEP_LEN,
    _TB_FRAMES,
    _TOKEN_RE,
    _condensed_tb,
    _location,
    _scrub_secrets,
    _shorten_path,
    build_error_message,
    scrub_text,
)
from .ship import (
    _SEND_BUDGET,
    _SEND_WINDOW,
    _ship_throttled,
    report_exc,
    report_record,
    send_to_log_errors,
    send_to_owner,
)
from .state import (
    _DEDUPE_WINDOW,
    _HEX_ADDR_RE,
    _MAX_CONTEXT_LEN,
    _OWNER_BUDGET,
    _OWNER_MAX,
    _OWNER_WINDOW,
    _RECENT_MAX,
    _TASK_ID_RE,
    _dedup,
    _fingerprint_exc,
    _fingerprint_record,
    _normalize_fp_text,
    _owner_sent,
    _owner_suppressed,
    _recent,
    _seen_recently,
    attach,
    log,
    set_owner,
)


def __getattr__(name: str) -> Any:
    """Delegate mutable scalar state to the owning submodule at read time."""
    if name in ("_bot", "_chat_id", "_thread_id", "_owner_id"):
        return getattr(_state, name)
    if name in ("_send_window_start", "_sent_in_window", "_suppressed_in_window"):
        return getattr(_ship, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "_ACTION_HINTS",
    "_BENIGN_PATTERNS",
    "_DEDUPE_WINDOW",
    "_HEX_ADDR_RE",
    "_LOG_NOISE_PATTERNS",
    "_MAX_CONTEXT_LEN",
    "_MAX_CTX",
    "_MAX_LINE_CONTENT",
    "_MAX_MSG",
    "_MAX_TB",
    "_MONGO_AUTH_RE",
    "_OWNER_BUDGET",
    "_OWNER_MAX",
    "_OWNER_ONLY_TYPES",
    "_OWNER_WINDOW",
    "_RECENT_MAX",
    "_REPORT_SEP_LEN",
    "_SEND_BUDGET",
    "_SEND_WINDOW",
    "_TASK_ID_RE",
    "_TB_FRAMES",
    "_TOKEN_RE",
    "_action_hint",
    "_benign",
    "_classify",
    "_condensed_tb",
    "_dedup",
    "_fingerprint_exc",
    "_fingerprint_record",
    "_location",
    "_log_noise",
    "_normalize_fp_text",
    "_owner_only",
    "_owner_sent",
    "_owner_suppressed",
    "_recent",
    "_scrub_secrets",
    "_seen_recently",
    "_ship_throttled",
    "_shorten_path",
    "attach",
    "build_error_message",
    "cfg",
    "log",
    "report_exc",
    "report_record",
    "scrub_text",
    "send_to_log_errors",
    "send_to_owner",
    "set_owner",
]
