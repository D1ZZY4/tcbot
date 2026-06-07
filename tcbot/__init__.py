# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Configuration singleton: loads env vars into a frozen dataclass and exposes a thin cfg adapter."""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv("config.env"))

log = logging.getLogger(__name__)

# ─────────────────────── Module-level constants ──────────────────── #

# * Default TCP port for the Flask health-check server.
_DEFAULT_PORT: int = 5000

# * Error message emitted when OWNER_ID is missing or invalid.
_ERR_OWNER_ID: str = "OWNER_ID is required and must be a positive integer."

# ───────────────────────── Config Parsing ───────────────────────── #


def parse_list(raw: str) -> list[str]:
    """Safely evaluate a stringified list from env; fall back to raw comma-separated strings."""
    if not raw.strip():
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed]
    except (ValueError, SyntaxError) as exc:
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
    if "/" in raw:
        chat_str, thread_str = raw.split("/", 1)
        return int(chat_str), int(thread_str)
    return int(raw), None


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
    if not (uri.startswith("mongodb://") or uri.startswith("mongodb+srv://")):
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
    raw = os.getenv(key, "").strip()
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def _parse_log_level(raw: str) -> int:
    """Resolve a log-level name to its integer constant; unknown names fall back to INFO."""
    level = getattr(logging, raw.strip().upper(), None)
    if isinstance(level, int):
        return level
    log.warning("Invalid LOG_LEVEL '%s', defaulting to INFO.", raw)
    return logging.INFO


# ─────────────────── Immutable Config Dataclass ─────────────────── #


@dataclass(frozen=True)
class Configs:
    """Immutable configuration dataclass: all fields are loaded from environment variables."""

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
    appeal_log_handle: str
    proof_timeout_seconds: int
    appeal_timeout_seconds: int
    appeal_discussion_topic: int
    extend_group: str
    album_debounce_seconds: int
    log_level: int
    modules_load: list[str]
    modules_no_load: list[str]

    # * Properties below handle lazy type-casting from raw env strings.
    @property
    def port_int(self) -> int:
        """Parse the PORT env string into an int, falling back to 5000 on invalid values."""
        return parse_port(self.port)

    @property
    def main_group_id(self) -> int:
        """Return MAIN_GROUP as int, or 0 when the env variable is unset."""
        return int(self.main_group) if self.main_group else 0

    @property
    def main_channel_id(self) -> int:
        """Return MAIN_CHANNEL as int, or 0 when the env variable is unset."""
        return int(self.main_channel) if self.main_channel else 0

    @property
    def extend_group_id(self) -> int:
        """Return EXTEND_GROUP as int, or 0 when the env variable is unset."""
        return int(self.extend_group) if self.extend_group else 0

    @property
    def logs_tuple(self) -> tuple[int, int | None]:
        """Parse the LOGS destination string into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.logs)

    @property
    def proofs_id(self) -> tuple[int, int | None]:
        """Parse the PROOFS destination string into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.proofs)

    @property
    def logs_errors_id(self) -> tuple[int, int | None]:
        """Parse the LOGS_ERRORS destination string into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.logs_errors)

    @property
    def appeals_id(self) -> tuple[int, int | None]:
        """Parse the APPEALS destination string into a (chat_id, thread_id) tuple."""
        return parse_chat_id(self.appeals)

    @staticmethod
    def load(env_file: str = "config.env") -> Configs:
        """Load all configuration from environment variables and return a Configs instance."""
        load_dotenv(find_dotenv(env_file))

        # ! BOT_TOKEN and MONGODB_URI are strictly required for runtime startup.
        token = _required_env("BOT_TOKEN")
        _warn_bot_token_fmt(token)
        mongodb_uri = _required_env("MONGODB_URI")
        _warn_mongodb_uri_fmt(mongodb_uri)

        owner_id = _owner_id_from_env()

        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = parse_list(raw_prefixes) or ["/"]

        db_name = os.getenv("DB_NAME", "tcbot").strip() or "tcbot"

        return Configs(
            bot_token=token,
            owner_id=owner_id,
            mongodb_uri=mongodb_uri,
            db_name=db_name,
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip(),
            prefixes=prefixes,
            port=os.getenv("PORT", str(_DEFAULT_PORT)).strip(),
            main_group=os.getenv("MAIN_GROUP", "").strip(),
            main_channel=os.getenv("MAIN_CHANNEL", "").strip(),
            proofs=os.getenv("PROOFS", "").strip(),
            logs=os.getenv("LOGS", "").strip(),
            logs_errors=os.getenv("LOGS_ERRORS", "").strip(),
            appeals=os.getenv("APPEALS", "").strip(),
            appeal_log_handle=os.getenv(
                "APPEAL_LOG_HANDLE", "@TranssionCoreFederationLogs"
            ).strip()
            or "@TranssionCoreFederationLogs",
            proof_timeout_seconds=_int_from_env(
                "PROOF_TIMEOUT_SECONDS", 100, minimum=1
            ),
            appeal_timeout_seconds=_int_from_env(
                "APPEAL_TIMEOUT_SECONDS", 600, minimum=1
            ),
            appeal_discussion_topic=_int_from_env("APPEAL_DISCUSSION_TOPIC", 0),
            extend_group=os.getenv("EXTEND_GROUP", "").strip(),
            album_debounce_seconds=_int_from_env(
                "ALBUM_DEBOUNCE_SECONDS", 2, minimum=1
            ),
            log_level=_parse_log_level(os.getenv("LOG_LEVEL", "INFO")),
            modules_load=_env_list("MODULES_LOAD"),
            modules_no_load=_env_list("MODULES_NO_LOAD"),
        )


configs = Configs.load()


# ! Property names in _CfgAdapter are imported by every module; rename with caution.
class _CfgAdapter:
    """Thin adapter that exposes Configs fields with the short canonical names used by all modules."""

    def __init__(self, c: Configs) -> None:
        self._c = c

    @property
    def bot_token(self) -> str:
        """Telegram bot token from BOT_TOKEN."""
        return self._c.bot_token

    @property
    def initial_owner_id(self) -> int:
        """Telegram user ID of the initial Founder seeded on first startup."""
        return self._c.owner_id

    @property
    def community_name(self) -> str:
        """Display name for the community used in bot messages and logs."""
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
        """List of command prefix characters (e.g. ['/', '!', '.'])."""
        return self._c.prefixes

    @property
    def port(self) -> int:
        """Flask health-check port as int; falls back to 5000 for invalid values."""
        return self._c.port_int

    @property
    def main_group(self) -> int:
        """Main community group chat ID, or 0 when unset."""
        return self._c.main_group_id

    @property
    def main_channel(self) -> int:
        """Announcement channel chat ID, or 0 when unset."""
        return self._c.main_channel_id

    @property
    def exec_group(self) -> int:
        """Staff/exec group chat ID, or 0 when unset."""
        return self._c.extend_group_id

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
    def appeal_log_handle(self) -> str:
        """Public log handle shown to users in appeal instructions."""
        return self._c.appeal_log_handle

    @property
    def proof_timeout(self) -> int:
        """Ban proof upload timeout in seconds."""
        return self._c.proof_timeout_seconds

    @property
    def appeal_timeout(self) -> int:
        """Appeal conversation inactivity timeout in seconds."""
        return self._c.appeal_timeout_seconds

    @property
    def appeal_discussion_topic(self) -> int:
        """Thread ID inside MAIN_GROUP where appeal review cards are posted."""
        return self._c.appeal_discussion_topic

    @property
    def album_debounce(self) -> int:
        """Album grouping window in seconds for multi-photo ban proofs."""
        return self._c.album_debounce_seconds

    @property
    def log_level(self) -> int:
        """Logging verbosity level as a stdlib logging int constant."""
        return self._c.log_level

    @property
    def modules_load(self) -> list[str]:
        """Optional allowlist of module names to load; empty means load all."""
        return self._c.modules_load

    @property
    def modules_no_load(self) -> list[str]:
        """Optional denylist of module names to skip during loading."""
        return self._c.modules_no_load


# * This adapter instance is the single global 'cfg' used by every module.
cfg = _CfgAdapter(configs)
