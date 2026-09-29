# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Env parsing helpers for configuration values."""

from __future__ import annotations

import ast
import logging
import os
import re
import secrets

log = logging.getLogger(__name__)

# * Default TCP port for the Flask health-check / webhook server.
_DEFAULT_PORT: int = 5000

# * Error message emitted when OWNER_ID is missing or invalid.
_ERR_OWNER_ID: str = "OWNER_ID is required and must be a positive integer."

# * Replit environment variable that exposes the dev domain (always HTTPS).
_REPLIT_DEV_DOMAIN_VAR: str = "REPLIT_DEV_DOMAIN"

# * Built-in Additional Links menu URLs. Used when the matching env var is
# * unset or blank; a non-empty env value always wins. Kept here (not in the
# * template) so fresh deployments show the community buttons with zero setup.
_DEFAULT_COMMUNITY_CHANNEL_URL: str = "https://t.me/TranssionCoreFederation"
_DEFAULT_COMMUNITY_GROUP_URL: str = "https://t.me/TranssionCoreFederationGroup"
_DEFAULT_COMMUNITY_LOGS_URL: str = "https://t.me/TranssionCoreFederationLogs"
_DEFAULT_COMMUNITY_EXEC_URL: str = "https://t.me/+A105pfnCvkhiZWM1"
_DEFAULT_COMMUNITY_TRAVEL_URL: str = "https://t.me/+S2C_ppFvHlAwMzNl"


def parse_list(raw: str) -> list[str]:
    """Safely evaluate a stringified list from env; fall back to raw comma-separated strings."""
    if not raw.strip():
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed]
    except ValueError as exc:
        logging.getLogger(__name__).debug(
            "parse_list falling back to CSV parsing: %s", exc
        )
    except SyntaxError as exc:
        logging.getLogger(__name__).debug(
            "parse_list falling back to CSV parsing: %s", exc
        )
    items = raw.strip("[]").split(",")
    return [item.strip().strip("'\"") for item in items if item.strip()]


def parse_port(port_str: str) -> int:
    """Resolve a port string to a valid TCP port; 'auto' or empty defaults to _DEFAULT_PORT."""
    if not port_str or port_str.lower() == "auto":
        return _DEFAULT_PORT
    try:
        port = int(port_str)
    except ValueError:
        log.warning("Invalid PORT '%s', defaulting to %d.", port_str, _DEFAULT_PORT)
        return _DEFAULT_PORT
    if 1 <= port <= 65_535:
        return port
    log.warning(
        "PORT '%s' is outside 1-65535, defaulting to %d.", port_str, _DEFAULT_PORT
    )
    return _DEFAULT_PORT


def parse_chat_id(raw: str) -> tuple[int, int | None]:
    """Parse a CHAT_ID or CHAT_ID/THREAD_ID env string into (chat_id, thread_id | None)."""
    if not raw:
        return 0, None
    try:
        if "/" in raw:
            chat_str, thread_str = raw.split("/", 1)
            return int(chat_str), int(thread_str)
        return int(raw), None
    except ValueError:
        log.warning("Invalid CHAT_ID format '%s', defaulting to 0.", raw)
        return 0, None
    except TypeError:
        log.warning("Invalid CHAT_ID format '%s', defaulting to 0.", raw)
        return 0, None


def _owner_id_from_env() -> int:
    """Read OWNER_ID and require a positive integer."""
    raw = os.getenv("OWNER_ID")
    if raw is None or not raw.strip():
        raise RuntimeError(_ERR_OWNER_ID)
    try:
        owner_id = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(_ERR_OWNER_ID) from exc
    if owner_id <= 0:
        raise RuntimeError(_ERR_OWNER_ID)
    return owner_id


def _required_env(key: str) -> str:
    """Return a required env var or raise a clear startup error without exposing values."""
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is required but not set.")
    return value


def _warn_bot_token_fmt(token: str) -> None:
    """Log a WARNING if the token does not match the Telegram bot-token pattern."""
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{35}", token):
        log.warning(
            "BOT_TOKEN format looks unexpected (expected <digits>:<35chars>). "
            "PTB will fail at startup if the value is wrong."
        )


def _warn_mongodb_uri_fmt(uri: str) -> None:
    """Log a WARNING if the MongoDB URI does not start with a recognised scheme."""
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        log.warning(
            "MONGODB_URI does not start with 'mongodb://' or 'mongodb+srv://'. "
            "Motor will fail at connect time if the value is wrong."
        )


def _int_from_env(key: str, default: int, *, minimum: int | None = None) -> int:
    """Read an integer env var, returning default on parse error or out-of-range values."""
    raw = os.getenv(key, str(default))
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid integer for %s, using %d.", key, default)
        return default
    if minimum is not None and value < minimum:
        log.warning("%s must be >= %d, using %d.", key, minimum, default)
        return default
    return value


def _env_list(key: str) -> list[str]:
    """Read an env var into a stripped name list; accepts CSV or a literal list."""
    return parse_list(os.getenv(key, "") or "")


def _parse_log_level(raw: str) -> int:
    """Resolve a log-level name to its integer constant; unknown names fall back to INFO."""
    level = getattr(logging, raw.strip().upper(), None)
    if isinstance(level, int):
        return level
    log.warning("Invalid LOG_LEVEL '%s', defaulting to INFO.", raw)
    return logging.INFO


def _auto_webhook_url() -> str:
    """Build the public webhook base URL from env vars with Replit auto-detection.

    Priority:
    1. WEBHOOK_URL env var (explicit override, any environment).
    2. REPLIT_DEV_DOMAIN env var (Replit auto-detection, always HTTPS).
    3. Empty string: no public URL available; bot falls back to polling (local dev only).
    """
    explicit = os.getenv("WEBHOOK_URL", "").strip()
    if explicit:
        if (
            explicit.startswith("http://")
            and "localhost" not in explicit
            and "127.0.0.1" not in explicit
        ):
            log.warning(
                "WEBHOOK_URL uses plain HTTP; Telegram requires HTTPS outside "
                "localhost and will refuse the registration."
            )
        return explicit.rstrip("/")

    replit_domain = os.getenv(_REPLIT_DEV_DOMAIN_VAR, "").strip()
    if replit_domain:
        return f"https://{replit_domain}"

    return ""


def _resolve_webhook_secret() -> str:
    """Return WEBHOOK_SECRET from env, or generate a cryptographically random token.

    A generated token changes every restart, but that is safe because set_webhook()
    is always called with the current token at startup, keeping Telegram in sync.
    """
    explicit = os.getenv("WEBHOOK_SECRET", "").strip()
    return explicit if explicit else secrets.token_hex(32)
