# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configuration singleton: env parsing, Configs dataclass, and cfg adapter."""

from __future__ import annotations

import ast
import os
import re
import secrets
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# ─────────────────────────────── Env parsing ─────────────────────────────── #

_DEFAULT_PORT: int = 5000
_DEFAULT_PROOFS: str = "-1003997518221"
_ERR_OWNER_ID: str = "OWNER_ID is required and must be a positive integer."
_REPLIT_DEV_DOMAIN_VAR: str = "REPLIT_DEV_DOMAIN"
_DEFAULT_COMMUNITY_CHANNEL_URL: str = "https://t.me/TranssionCoreFederation"
_DEFAULT_COMMUNITY_GROUP_URL: str = "https://t.me/TranssionCoreFederationGroup"
_DEFAULT_COMMUNITY_LOGS_URL: str = "https://t.me/TranssionCoreFederationLogs"
_DEFAULT_COMMUNITY_APPEAL_URL: str = "https://t.me/TranssionCoreFederationAppeals"
_DEFAULT_COMMUNITY_TRAVEL_URL: str = "https://t.me/+S2C_ppFvHlAwMzNl"

# * Numeric levels for ``cfg.log_level`` (stdlib-compatible ints consumed by
# * ``utils.logger.setup``); WARN and FATAL are kept as aliases.
_LOG_LEVELS: dict[str, int] = {
    "NOTSET": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "WARN": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}


def tme_handle_from_url(url: str) -> str:
    """Return display handle ``@name`` for a ``https://t.me/`` URL."""
    name = url.strip().removeprefix("https://t.me/").strip("/")
    return "@" + name if name and "/" not in name and "+" not in name else url.strip()


def parse_list(raw: str) -> list[str]:
    """Safely evaluate a stringified list, falling back to CSV parsing."""
    if not raw.strip():
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed]
    except (ValueError, SyntaxError) as exc:
        log.debug("parse_list falling back to CSV parsing: %s", exc)
    items = raw.strip("[]").split(",")
    return [item.strip().strip("'\"") for item in items if item.strip()]


def parse_port(port_str: str) -> int:
    """Resolve a port string; ``auto`` or invalid defaults to 5000."""
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
    """Parse ``CHAT_ID`` or ``CHAT_ID/THREAD_ID`` into a tuple."""
    if not raw:
        return 0, None
    try:
        if "/" in raw:
            chat_str, thread_str = raw.split("/", 1)
            return int(chat_str), int(thread_str)
        return int(raw), None
    except ValueError, TypeError:
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
    """Return a required env var or raise without exposing values."""
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is required but not set.")
    return value


def _warn_bot_token_fmt(token: str) -> None:
    """Warn if the token does not match the Telegram bot-token pattern."""
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{35}", token):
        log.warning(
            "BOT_TOKEN format looks unexpected (expected <digits>:<35chars>). "
            "PTB will fail at startup if the value is wrong."
        )


def _warn_mongodb_uri_fmt(uri: str) -> None:
    """Warn if the MongoDB URI does not start with a recognised scheme."""
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        log.warning(
            "MONGODB_URI does not start with 'mongodb://' or 'mongodb+srv://'. "
            "Motor will fail at connect time if the value is wrong."
        )


def _int_from_env(key: str, default: int, *, minimum: int | None = None) -> int:
    """Read an integer env var, returning default on bad or low values."""
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
    """Read an env var into a stripped list; accepts CSV or a literal list."""
    return parse_list(os.getenv(key, "") or "")


def _parse_log_level(raw: str) -> int:
    """Resolve a log-level name; unknown names fall back to INFO."""
    level = _LOG_LEVELS.get(raw.strip().upper())
    if level is not None:
        return level
    log.warning("Invalid LOG_LEVEL '%s', defaulting to INFO.", raw)
    return _LOG_LEVELS["INFO"]


def _auto_webhook_url() -> str:
    """Build the webhook base URL: WEBHOOK_URL, Replit domain, else empty."""
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
    return f"https://{replit_domain}" if replit_domain else ""


def _resolve_webhook_secret() -> str:
    """Return WEBHOOK_SECRET, generating a random token when unset."""
    explicit = os.getenv("WEBHOOK_SECRET", "").strip()
    return explicit if explicit else secrets.token_hex(32)


# ─────────────────────────────── Config model ────────────────────────────── #


@dataclass(frozen=True)
class Configs:
    """Immutable configuration loaded from environment variables."""

    bot_token: str
    owner_id: int
    mongodb_uri: str
    db_name: str
    community_name: str
    prefixes: list[str]
    port: str
    main_group: str
    main_channel: str
    proofs: str
    logs: str
    logs_errors: str
    appeals: str
    album_debounce_seconds: int
    log_level: int
    modules_load: list[str]
    modules_no_load: list[str]
    redis_url: str | None
    warn_expiry_days: int
    sync_interval_hours: int
    fed_warn_limit: int
    warn_limit: int
    webhook_url: str
    webhook_secret: str
    webhook_secret_explicit: str
    cron_secret: str
    community_channel_url: str
    community_group_url: str
    community_logs_url: str
    community_appeal_url: str
    community_travel_url: str
    api_id: int
    api_hash: str
    mtproto_session: str

    @property
    def port_int(self) -> int:
        """Parse PORT into an int, falling back to 5000 on invalid values."""
        return parse_port(self.port)

    @property
    def main_group_id(self) -> int:
        """Return MAIN_GROUP as int, or 0 when unset or invalid."""
        if not self.main_group:
            return 0
        try:
            return int(self.main_group)
        except ValueError:
            log.warning("Invalid MAIN_GROUP '%s', defaulting to 0.", self.main_group)
            return 0

    @property
    def main_channel_id(self) -> int:
        """Return MAIN_CHANNEL as int, or 0 when unset or invalid."""
        if not self.main_channel:
            return 0
        try:
            return int(self.main_channel)
        except ValueError:
            log.warning(
                "Invalid MAIN_CHANNEL '%s', defaulting to 0.", self.main_channel
            )
            return 0

    @property
    def logs_tuple(self) -> tuple[int, int | None]:
        """Parse LOGS into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.logs)

    @property
    def proofs_id(self) -> tuple[int, int | None]:
        """Parse PROOFS into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.proofs)

    @property
    def logs_errors_id(self) -> tuple[int, int | None]:
        """Parse LOGS_ERRORS into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.logs_errors)

    @property
    def appeals_id(self) -> tuple[int, int | None]:
        """Parse APPEALS into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.appeals)

    @staticmethod
    def load(env_file: str = "config.env") -> Configs:
        """Load configuration from environment variables."""
        load_dotenv(find_dotenv(env_file) or find_dotenv(".env"))
        token = _required_env("BOT_TOKEN")
        _warn_bot_token_fmt(token)
        mongodb_uri = _required_env("MONGODB_URI")
        _warn_mongodb_uri_fmt(mongodb_uri)
        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = parse_list(raw_prefixes) or ["/", "!", "."]
        return Configs(
            bot_token=token,
            owner_id=_owner_id_from_env(),
            mongodb_uri=mongodb_uri,
            db_name=os.getenv("DB_NAME", "tcbot").strip() or "tcbot",
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip() or "Bot",
            prefixes=prefixes,
            port=os.getenv("PORT", str(_DEFAULT_PORT)).strip(),
            main_group=os.getenv("MAIN_GROUP", "").strip(),
            main_channel=os.getenv("MAIN_CHANNEL", "").strip(),
            proofs=os.getenv("PROOFS", "").strip() or _DEFAULT_PROOFS,
            logs=os.getenv("LOGS", "").strip(),
            logs_errors=os.getenv("LOGS_ERRORS", "").strip(),
            appeals=os.getenv("APPEALS", "").strip(),
            album_debounce_seconds=_int_from_env(
                "ALBUM_DEBOUNCE_SECONDS", 4, minimum=1
            ),
            log_level=_parse_log_level(os.getenv("LOG_LEVEL", "INFO")),
            modules_load=_env_list("MODULES_LOAD"),
            modules_no_load=_env_list("MODULES_NO_LOAD"),
            redis_url=os.getenv("REDIS_URL", "").strip() or None,
            warn_expiry_days=_int_from_env("WARN_EXPIRY_DAYS", 0, minimum=0),
            sync_interval_hours=_int_from_env("SYNC_INTERVAL_HOURS", 0, minimum=0),
            fed_warn_limit=_int_from_env("FED_WARN_LIMIT", 0, minimum=0),
            warn_limit=_int_from_env("WARN_LIMIT", 3, minimum=1),
            webhook_url=_auto_webhook_url(),
            webhook_secret=_resolve_webhook_secret(),
            webhook_secret_explicit=os.getenv("WEBHOOK_SECRET", "").strip(),
            cron_secret=os.getenv("CRON_SECRET", "").strip(),
            community_channel_url=os.getenv(
                "COMMUNITY_CHANNEL_URL", _DEFAULT_COMMUNITY_CHANNEL_URL
            ).strip()
            or _DEFAULT_COMMUNITY_CHANNEL_URL,
            community_group_url=os.getenv(
                "COMMUNITY_GROUP_URL", _DEFAULT_COMMUNITY_GROUP_URL
            ).strip()
            or _DEFAULT_COMMUNITY_GROUP_URL,
            community_appeal_url=os.getenv(
                "COMMUNITY_APPEAL_URL", _DEFAULT_COMMUNITY_APPEAL_URL
            ).strip()
            or _DEFAULT_COMMUNITY_APPEAL_URL,
            community_logs_url=os.getenv(
                "COMMUNITY_LOGS_URL", _DEFAULT_COMMUNITY_LOGS_URL
            ).strip()
            or _DEFAULT_COMMUNITY_LOGS_URL,
            community_travel_url=os.getenv(
                "COMMUNITY_TRAVEL_URL", _DEFAULT_COMMUNITY_TRAVEL_URL
            ).strip()
            or _DEFAULT_COMMUNITY_TRAVEL_URL,
            api_id=_int_from_env("API_ID", 0, minimum=0),
            api_hash=os.getenv("API_HASH", "").strip(),
            mtproto_session=os.getenv("MTPROTO_SESSION", "tcbot_mtproto").strip()
            or "tcbot_mtproto",
        )


# ─────────────────────────────── cfg adapter ─────────────────────────────── #


class _CfgAdapter:
    """Thin adapter exposing Configs fields with short canonical names."""

    def __init__(self, c: Configs) -> None:
        self._c = c

    @property
    def bot_token(self) -> str:
        """Telegram bot token from BOT_TOKEN."""
        return self._c.bot_token

    @property
    def initial_owner_id(self) -> int:
        """Telegram user ID of the initial Founder."""
        return self._c.owner_id

    @property
    def community_name(self) -> str:
        """Display name used in bot messages and logs."""
        return self._c.community_name

    @property
    def mongodb_uri(self) -> str:
        """MongoDB connection string from MONGODB_URI."""
        return self._c.mongodb_uri

    @property
    def db_name(self) -> str:
        """MongoDB database name (defaults to 'tcbot')."""
        return self._c.db_name

    @property
    def prefixes(self) -> list[str]:
        """Command prefix characters (e.g. ['/', '!', '.'])."""
        return list(self._c.prefixes)

    @property
    def port(self) -> int:
        """Flask / webhook port; falls back to 5000 when invalid."""
        return self._c.port_int

    @property
    def main_group(self) -> int:
        """Main community group chat ID, or 0 when unset."""
        return self._c.main_group_id

    @property
    def main_channel(self) -> int:
        """Announcement channel chat ID, or 0 when unset."""
        return self._c.main_channel_id

    def is_primary_group(self, chat_id: int | None) -> bool:
        """Check whether the chat is the main group."""
        if chat_id is None or chat_id <= 0:
            return False
        return chat_id == self.main_group

    @property
    def logs(self) -> tuple[int, int | None]:
        """Moderation log destination as (chat_id, thread_id)."""
        return self._c.logs_tuple

    @property
    def logs_errors(self) -> tuple[int, int | None]:
        """Error report destination as (chat_id, thread_id)."""
        return self._c.logs_errors_id

    @property
    def proofs(self) -> tuple[int, int | None]:
        """Ban proof destination as (chat_id, thread_id)."""
        return self._c.proofs_id

    @property
    def appeals(self) -> tuple[int, int | None]:
        """Appeal record destination as (chat_id, thread_id)."""
        return self._c.appeals_id

    @property
    def album_debounce(self) -> int:
        """Album grouping window in seconds for ban proofs."""
        return self._c.album_debounce_seconds

    @property
    def log_level(self) -> int:
        """Logging verbosity as a stdlib logging int constant."""
        return self._c.log_level

    @property
    def modules_load(self) -> list[str]:
        """Optional allowlist of module names; empty means load all."""
        return self._c.modules_load

    @property
    def modules_no_load(self) -> list[str]:
        """Optional denylist of module names to skip."""
        return self._c.modules_no_load

    @property
    def redis_url(self) -> str | None:
        """Redis URL from REDIS_URL (None when not configured)."""
        return self._c.redis_url

    @property
    def warn_expiry_days(self) -> int:
        """Days before warn records expire; 0 = disabled."""
        return self._c.warn_expiry_days

    @property
    def sync_interval_hours(self) -> int:
        """Hours between scheduled sync sweeps; 0 = disabled."""
        return self._c.sync_interval_hours

    @property
    def fed_warn_limit(self) -> int:
        """Federation-wide warn threshold for threshold ban; 0 = disabled."""
        return self._c.fed_warn_limit

    @property
    def warn_limit(self) -> int:
        """Per-group warn threshold for threshold ban (minimum 1, default 3)."""
        return self._c.warn_limit

    @property
    def webhook_url(self) -> str:
        """Public webhook base URL; empty means polling fallback."""
        return self._c.webhook_url

    @property
    def webhook_secret(self) -> str:
        """Secret token Telegram sends in the webhook header."""
        return self._c.webhook_secret

    @property
    def webhook_secret_explicit(self) -> str:
        """Explicit WEBHOOK_SECRET; empty when unset (no generated fallback)."""
        return self._c.webhook_secret_explicit

    @property
    def cron_secret(self) -> str:
        """Bearer token for the serverless cron endpoint."""
        return self._c.cron_secret

    @property
    def is_webhook_mode(self) -> bool:
        """True when a public webhook URL is available."""
        return bool(self._c.webhook_url)

    @property
    def community_channel_url(self) -> str:
        """Public URL of the main community channel."""
        return self._c.community_channel_url

    @property
    def community_group_url(self) -> str:
        """Public URL of the main community discussion group."""
        return self._c.community_group_url

    @property
    def community_appeal_url(self) -> str:
        """Public URL of the appeals channel."""
        return self._c.community_appeal_url

    @property
    def community_logs_url(self) -> str:
        """Public URL of the logs channel."""
        return self._c.community_logs_url

    @property
    def community_travel_url(self) -> str:
        """Public URL or invite link of the TRAVEL community."""
        return self._c.community_travel_url

    @property
    def mtproto_enabled(self) -> bool:
        """True when API_ID + API_HASH are set."""
        return self._c.api_id > 0 and bool(self._c.api_hash)

    @property
    def api_id(self) -> int:
        """Telegram API ID for MTProto, or 0 when not configured."""
        return self._c.api_id

    @property
    def api_hash(self) -> str:
        """Telegram API hash for MTProto (empty when not configured)."""
        return self._c.api_hash

    @property
    def mtproto_session(self) -> str:
        """Namespace for the shared MTProto session in MongoDB."""
        return self._c.mtproto_session


configs = Configs.load()
cfg = _CfgAdapter(configs)

__all__ = [
    "Configs",
    "_CfgAdapter",
    "_env_list",
    "cfg",
    "configs",
    "parse_chat_id",
    "parse_list",
    "parse_port",
    "tme_handle_from_url",
]
