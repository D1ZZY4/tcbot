# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configuration singleton: env parsing and the immutable Configs model."""

from __future__ import annotations

import ast
import os
import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotenv import find_dotenv, load_dotenv

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    # * The configuration is built on first access (see ``__getattr__``).
    # * The declaration keeps the type checker aware of the attribute the
    # * module exposes at runtime.
    cfg: Configs

log = get_logger(__name__)

# ─────────────────────────────── Env parsing ─────────────────────────────── #

_DEFAULT_PORT: int = 5000
_DEFAULT_PROOFS: str = "-1003997518221"
_ERR_OWNER_ID: str = "OWNER_ID is required and must be a positive integer."
# * The connection pool of the database. The size has to fit the number
# * of connections the database grants this user: a pooler in session or
# * transaction mode caps it at a small number, and a pool that is larger
# * than the cap does not fail at startup. It fails later, as a "max
# * clients reached" refusal on every call that needs a connection, and
# * the circuit breaker reads that refusal as an outage of the database.
_DEFAULT_DB_POOL_SIZE: int = 5
_DEFAULT_DB_MAX_OVERFLOW: int = 5
# * The schema the application reads and writes. The deployment owns
# * "public", the integration tests own "test", and a developer owns
# * "development". Those three are the only schemas this project uses,
# * so a stray schema cannot hide a migration that never ran.
_DEFAULT_DB_SCHEMA: str = "public"
# * A schema name reaches the server as part of a connection option, so
# * it has to be a plain identifier. Anything else is refused instead of
# * being quoted into the option string.
_DB_SCHEMA_PATTERN: re.Pattern[str] = re.compile(r"^[a-z_][a-z0-9_]*$")
_REPLIT_DEV_DOMAIN_VAR: str = "REPLIT_DEV_DOMAIN"
_DEFAULT_COMMUNITY_CHANNEL_URL: str = "https://t.me/TranssionCoreFederation"
_DEFAULT_COMMUNITY_GROUP_URL: str = "https://t.me/TranssionCoreFederationGroup"
_DEFAULT_COMMUNITY_LOGS_URL: str = "https://t.me/TranssionCoreFederationLogs"
_DEFAULT_COMMUNITY_APPEAL_URL: str = "https://t.me/TranssionCoreFederationAppeals"
# * The Replit dev domain is only usable when this process is the one the
# * Replit platform exposes. The variable is also set in a workspace shell
# * that starts the bot by hand, and the dev domain there points at the
# * Replit workflow, not at the shell. Registering it from the shell moves
# * every update to another process, so the bot answers nothing while it
# * looks perfectly healthy.
# *
# * These variables exist only in the Replit runtime, so one of them proves
# * the process is the app. An operator who runs the bot somewhere else and
# * wants the webhook anyway sets ``WEBHOOK_URL`` explicitly.
_REPLIT_RUNTIME_MARKERS: tuple[str, ...] = (
    "REPLIT_SLUG",
    "REPLIT_OWNER",
    "REPLIT_APP_NAME",
    "REPLIT_IDENTITY",
    "REPLIT_DEPLOYMENT",
)

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


def _warn_database_url_fmt(url: str) -> None:
    """Warn if the database URL does not start with a recognised scheme."""
    if not url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        log.warning(
            "DATABASE_URL does not start with 'postgresql://'. "
            "The database client will fail at connect time if the value is wrong."
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


def _on_replit() -> bool:
    """Return True when this process runs as the Replit application.

    The check looks for a variable the Replit runtime sets and nothing
    else sets. A workspace shell inherits the dev domain but none of these,
    so a bot started by hand there is not the process the platform
    exposes.
    """
    return any(os.getenv(marker, "").strip() for marker in _REPLIT_RUNTIME_MARKERS)


def _auto_webhook_url() -> str:
    """Build the webhook base URL: WEBHOOK_URL, the Replit dev domain, else empty."""
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
    if not replit_domain:
        return ""
    if not _on_replit():
        # * The dev domain belongs to the Replit workflow, not to this
        # * process. Registering it here would hand every update to another
        # * process, so the bot would look healthy and answer nothing.
        # * Polling is the local fallback and reaches the same bot.
        log.warning(
            "%s is set but this process is not the Replit application; "
            "falling back to polling. Set WEBHOOK_URL to use a webhook "
            "anyway.",
            _REPLIT_DEV_DOMAIN_VAR,
        )
        return ""
    return f"https://{replit_domain}"


def _resolve_webhook_secret() -> str:
    """Return WEBHOOK_SECRET, generating a random token when unset."""
    explicit = os.getenv("WEBHOOK_SECRET", "").strip()
    return explicit if explicit else secrets.token_hex(32)


def _chat_id_from_env(key: str) -> int:
    """Read a plain chat-id env var; unset or invalid values resolve to 0."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s '%s', defaulting to 0.", key, raw)
        return 0


def _env_or(key: str, default: str) -> str:
    """Read an env var, falling back to *default* when it is blank."""
    return os.getenv(key, "").strip() or default


def _db_schema_from_env() -> str:
    """Read the schema the application works in.

    The value reaches the server as a connection option, so only a plain
    identifier is accepted. An unusable name falls back to the default
    rather than producing a connection that fails on every call.
    """
    raw = os.getenv("DB_SCHEMA", "").strip() or _DEFAULT_DB_SCHEMA
    if not _DB_SCHEMA_PATTERN.fullmatch(raw):
        log.warning(
            "Invalid DB_SCHEMA '%s'; using %s. The name has to be a plain "
            "PostgreSQL identifier.",
            raw,
            _DEFAULT_DB_SCHEMA,
        )
        return _DEFAULT_DB_SCHEMA
    return raw


# ─────────────────────────────── Config model ────────────────────────────── #


@dataclass(frozen=True)
class Configs:
    """Immutable runtime configuration loaded from environment variables.

    Every field is already parsed and validated: consumers never re-parse
    env values, so an invalid setting fails once at load time instead of
    silently degrading at every call site.
    """

    bot_token: str
    initial_owner_id: int
    database_url: str
    community_name: str
    prefixes: tuple[str, ...]
    port: int
    main_group: int
    logs: tuple[int, int | None]
    logs_errors: tuple[int, int | None]
    proofs: tuple[int, int | None]
    appeals: tuple[int, int | None]
    album_debounce: int
    log_level: int
    modules_load: tuple[str, ...]
    modules_no_load: tuple[str, ...]
    redis_url: str | None
    db_pool_size: int
    db_max_overflow: int
    db_schema: str
    warn_expiry_days: int
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
    api_id: int
    api_hash: str
    mtproto_session: str
    sentry_dsn: str

    def is_primary_group(self, chat_id: int | None) -> bool:
        """Check whether the chat is the main group.

        ``0`` is the unset sentinel for an unconfigured ``MAIN_GROUP``.
        Telegram group and channel IDs are negative, so only that exact
        sentinel is rejected: a ``<= 0`` guard would silently exclude every
        real group and never match the primary group at all.
        """
        if chat_id is None or chat_id == 0 or self.main_group == 0:
            return False
        return chat_id == self.main_group

    @property
    def is_webhook_mode(self) -> bool:
        """True when a public webhook URL is available."""
        return bool(self.webhook_url)

    @property
    def mtproto_enabled(self) -> bool:
        """True when API_ID + API_HASH are set."""
        return self.api_id > 0 and bool(self.api_hash)

    @staticmethod
    def load(env_file: str = "config.env") -> Configs:
        """Load configuration from environment variables."""
        load_dotenv(find_dotenv(env_file) or find_dotenv(".env"))
        token = _required_env("BOT_TOKEN")
        _warn_bot_token_fmt(token)
        database_url = _required_env("DATABASE_URL")
        _warn_database_url_fmt(database_url)
        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = tuple(parse_list(raw_prefixes) or ["/", "!", "."])
        return Configs(
            bot_token=token,
            initial_owner_id=_owner_id_from_env(),
            database_url=database_url,
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip() or "Bot",
            prefixes=prefixes,
            port=parse_port(os.getenv("PORT", str(_DEFAULT_PORT)).strip()),
            main_group=_chat_id_from_env("MAIN_GROUP"),
            logs=parse_chat_id(os.getenv("LOGS", "").strip()),
            logs_errors=parse_chat_id(os.getenv("LOGS_ERRORS", "").strip()),
            proofs=parse_chat_id(os.getenv("PROOFS", "").strip() or _DEFAULT_PROOFS),
            appeals=parse_chat_id(os.getenv("APPEALS", "").strip()),
            album_debounce=_int_from_env("ALBUM_DEBOUNCE_SECONDS", 4, minimum=1),
            log_level=_parse_log_level(os.getenv("LOG_LEVEL", "INFO")),
            modules_load=tuple(_env_list("MODULES_LOAD")),
            modules_no_load=tuple(_env_list("MODULES_NO_LOAD")),
            redis_url=os.getenv("REDIS_URL", "").strip() or None,
            db_pool_size=_int_from_env(
                "DB_POOL_SIZE", _DEFAULT_DB_POOL_SIZE, minimum=1
            ),
            db_max_overflow=_int_from_env(
                "DB_MAX_OVERFLOW", _DEFAULT_DB_MAX_OVERFLOW, minimum=0
            ),
            db_schema=_db_schema_from_env(),
            warn_expiry_days=_int_from_env("WARN_EXPIRY_DAYS", 0, minimum=0),
            fed_warn_limit=_int_from_env("FED_WARN_LIMIT", 0, minimum=0),
            warn_limit=_int_from_env("WARN_LIMIT", 3, minimum=1),
            webhook_url=_auto_webhook_url(),
            webhook_secret=_resolve_webhook_secret(),
            webhook_secret_explicit=os.getenv("WEBHOOK_SECRET", "").strip(),
            cron_secret=os.getenv("CRON_SECRET", "").strip(),
            community_channel_url=_env_or(
                "COMMUNITY_CHANNEL_URL", _DEFAULT_COMMUNITY_CHANNEL_URL
            ),
            community_group_url=_env_or(
                "COMMUNITY_GROUP_URL", _DEFAULT_COMMUNITY_GROUP_URL
            ),
            community_appeal_url=_env_or(
                "COMMUNITY_APPEAL_URL", _DEFAULT_COMMUNITY_APPEAL_URL
            ),
            community_logs_url=_env_or(
                "COMMUNITY_LOGS_URL", _DEFAULT_COMMUNITY_LOGS_URL
            ),
            api_id=_int_from_env("API_ID", 0, minimum=0),
            api_hash=os.getenv("API_HASH", "").strip(),
            mtproto_session=_env_or("MTPROTO_SESSION", "tcbot_mtproto"),
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
        )


# * The configuration is built on first access (PEP 562) instead of at
# * import time. Importing the package must not require the bot
# * credentials: the Alembic environment, the migration generator, and
# * the test collection all import ``tcbot`` submodules without a
# * running bot. The first read still fails fast when a required
# * setting is missing, and the bot reads it while starting up.
_cfg: Configs | None = None


def __getattr__(name: str) -> Configs:
    """Return the configuration singleton, building it on first access."""
    if name != "cfg":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    global _cfg
    if _cfg is None:
        _cfg = Configs.load()
        # * Cache it as a real module attribute so later reads skip this hook.
        globals()["cfg"] = _cfg
    return _cfg


__all__ = [
    "Configs",
    "cfg",
    "parse_chat_id",
    "parse_list",
    "parse_port",
    "tme_handle_from_url",
]
