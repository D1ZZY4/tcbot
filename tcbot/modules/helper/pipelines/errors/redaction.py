# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Secret redaction for console output, report payloads, and monitoring hooks."""

from __future__ import annotations

import re
from typing import Any

from tcbot import cfg

# * No leading word boundary: a token inside "bot<token>/..." must still be
# * redacted when the exact configured value is unavailable.
_TOKEN_RE = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{20,}\b")
_URL_CREDENTIALS_RE = re.compile(r"://(?:[^:@/\s]+)?:[^@/\s]+@")


def _scrub_secrets(text: str) -> str:
    """Redact exact configured values first, then credential-shaped patterns.

    A fatal startup report can run when the configuration itself failed to
    load. Reading ``cfg`` would raise again and mask the original error, so
    the configured-value pass degrades to the shape-based redaction below.
    """
    try:
        configured = (
            getattr(cfg, "bot_token", ""),
            getattr(cfg, "database_url", ""),
            getattr(cfg, "api_hash", ""),
            getattr(cfg, "redis_url", ""),
            getattr(cfg, "sentry_dsn", ""),
        )
    except Exception:
        configured = ()
    for secret in configured:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _URL_CREDENTIALS_RE.sub("://[REDACTED]@", text)


def scrub_text(text: str) -> str:
    """Public wrapper for secret redaction of console-bound strings."""
    return _scrub_secrets(text)


def _scrub_event_value(value: object) -> object:
    """Recursively redact string leaves in a Sentry event payload."""
    if isinstance(value, str):
        return _scrub_secrets(value)
    if isinstance(value, dict):
        return {str(key): _scrub_event_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_event_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_event_value(item) for item in value)
    return value


def scrub_sentry_event(event: Any, hint: Any = None) -> Any:
    """Redact credential-bearing strings before a Sentry event is delivered.

    Used as the ``before_send`` hook, so non-string values such as retry
    counters must survive unchanged and the event structure must be kept.
    The SDK is an optional extra, so its ``Event`` type cannot be imported
    here without breaking checks in installations that omit it; the hook
    is duck-typed against the event mapping at runtime.
    """
    _ = hint
    return {key: _scrub_event_value(value) for key, value in event.items()}


__all__ = ["scrub_sentry_event", "scrub_text"]
