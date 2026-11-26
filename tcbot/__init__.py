# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configuration singleton: env parsing and the immutable Configs model."""

from __future__ import annotations

import ast
import os
import re
import threading
from dataclasses import dataclass, field
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
# * The keep-alive listener binds every interface by default so
# * a container or hosted process is reachable. An operator behind a local
# * reverse proxy can set BIND_HOST=127.0.0.1.
_DEFAULT_BIND_HOST: str = "0.0.0.0"
_ERR_OWNER_ID: str = "OWNER_ID is required and must be a positive integer."
_ERR_PROOFS: str = "PROOFS is required and must be a valid group or channel chat id."
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
# * The complete set of schemas this project owns. A name outside it would
# * create a fourth schema at startup and hide migrations that never ran.
DB_SCHEMAS: frozenset[str] = frozenset({"public", "test", "development"})
# * A pending promotion request that is not decided within this window is
# * marked expired, so an old card cannot block a fresh request forever.
# * Zero disables the expiry and keeps requests pending indefinitely.
_DEFAULT_PROMOTION_REQUEST_TTL_DAYS: int = 7
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


def parse_list(raw: str) -> list[str]:
    """Safely evaluate a stringified list, falling back to CSV parsing."""
    if not raw.strip():
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            # * Drop blank entries in both forms: the CSV branch already does,
            # * and MODULES_LOAD treats an empty name as an invalid module.
            return [value for item in parsed if (value := str(item).strip())]
    except (ValueError, SyntaxError) as exc:
        # * This fallback can change command prefixes, registered modules, and
        # * the infrastructure-chat guard, so it must be visible at INFO level.
        log.warning("parse_list falling back to CSV parsing: %s", exc)
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
    """Parse ``CHAT_ID`` or ``CHAT_ID/THREAD_ID`` into a tuple.

    A thread id has to be positive; a zero or negative segment names no
    forum thread and is dropped instead of reaching Telegram as a
    ``message_thread_id`` the API refuses.
    """
    if not raw:
        return 0, None
    try:
        if "/" in raw:
            chat_str, thread_str = raw.split("/", 1)
            chat_id = int(chat_str)
            try:
                thread_id = int(thread_str)
            except ValueError:
                # * A bad thread segment must not discard an otherwise valid
                # * chat: the destination still works without a forum topic.
                thread_id = 0
            if thread_id <= 0:
                # * The value may name a private chat, so it stays out of
                # * the log; the operator already knows which variable it is.
                log.warning(
                    "Invalid CHAT_ID thread segment; using the chat without a thread."
                )
                return chat_id, None
            return chat_id, thread_id
        return int(raw), None
    except ValueError, TypeError:
        log.warning("Invalid CHAT_ID format, defaulting to 0.")
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


def _proofs_from_env() -> tuple[int, int | None]:
    """Read the required proof destination and refuse an unusable value.

    A ban requires landed evidence, so the destination cannot be optional.
    The deployment names it; the bot does not carry a community channel id
    of its own, because that would make every fork write to a chat it does
    not own.
    """
    raw = os.getenv("PROOFS", "").strip()
    if not raw:
        raise RuntimeError(_ERR_PROOFS)
    chat_id, thread_id = parse_chat_id(raw)
    # * A group or channel id is negative; a positive one names a user and
    # * cannot hold the evidence archive the schema records.
    if chat_id >= 0:
        raise RuntimeError(_ERR_PROOFS)
    return chat_id, thread_id


def _warn_bot_token_fmt(token: str) -> None:
    """Warn if the token does not match the Telegram bot-token pattern."""
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{35}", token):
        log.warning(
            "BOT_TOKEN format looks unexpected (expected <digits>:<35chars>). "
            "Telegram will refuse the login if the value is wrong."
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


# * Explicit worker override is capped: the application already bounds handler
# * concurrency, and thousands of dispatcher tasks would only contend for the
# * same small database pool.
_KURIGRAM_WORKERS_MAX: int = 64


def _workers_from_env() -> int:
    """Read the optional Kurigram worker override; 0 means automatic sizing."""
    raw = os.getenv("KURIGRAM_WORKERS", "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid KURIGRAM_WORKERS, using automatic sizing.")
        return 0
    if value < 1:
        log.warning("KURIGRAM_WORKERS must be positive, using automatic sizing.")
        return 0
    return min(value, _KURIGRAM_WORKERS_MAX)


def _env_list(key: str) -> list[str]:
    """Read an env var into a stripped list; accepts CSV or a literal list."""
    return parse_list(os.getenv(key, "") or "")


def _bool_from_env(key: str, *, default: bool = False) -> bool:
    """Read a boolean env var, warning and falling back on an unknown value."""
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    log.warning("Invalid boolean for %s, using %s.", key, default)
    return default


def _parse_log_level(raw: str) -> int:
    """Resolve a log-level name; unknown names fall back to INFO."""
    level = _LOG_LEVELS.get(raw.strip().upper())
    if level is not None:
        return level
    log.warning("Invalid LOG_LEVEL '%s', defaulting to INFO.", raw)
    return _LOG_LEVELS["INFO"]


def _infra_chat_ids_from_env() -> tuple[int, ...]:
    """Read extra deployment-owned chat ids from ``INFRA_CHAT_IDS``.

    Only negative chat ids are accepted: a positive value names a user and
    must never be treated as an infrastructure destination. Bad entries are
    skipped with a warning instead of weakening the guard.
    """
    ids: list[int] = []
    for raw in _env_list("INFRA_CHAT_IDS"):
        try:
            value = int(raw)
        except ValueError:
            log.warning("Ignoring non-numeric INFRA_CHAT_IDS entry.")
            continue
        if value < 0:
            ids.append(value)
        else:
            log.warning("Ignoring positive INFRA_CHAT_IDS entry.")
    return tuple(dict.fromkeys(ids))


def _chat_id_from_env(key: str) -> int:
    """Read a plain chat-id env var; unset or invalid values resolve to 0."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        # * The value may identify a private chat, so it stays out of the log.
        log.warning("Invalid %s value, defaulting to 0.", key)
        return 0


def _main_group_from_env() -> int:
    """Read ``MAIN_GROUP``; a group id has to be negative.

    Telegram group and channel ids are negative, so a positive value names
    a user and can never be the community group. The value is treated as
    unset instead of silently matching nothing or, worse, a private chat.
    """
    value = _chat_id_from_env("MAIN_GROUP")
    if value > 0:
        log.warning(
            "MAIN_GROUP must be a negative group chat id; treating the "
            "configured value as unset."
        )
        return 0
    return value


def _main_channel_from_env() -> int:
    """Read ``MAIN_CHANNEL``; a channel id has to be negative.

    The channel is the publication target for rules. A positive value
    names a user and cannot be a channel, so it is treated as unset.
    """
    value = _chat_id_from_env("MAIN_CHANNEL")
    if value > 0:
        log.warning(
            "MAIN_CHANNEL must be a negative channel chat id; treating the "
            "configured value as unset."
        )
        return 0
    return value


def _env_or(key: str, default: str) -> str:
    """Read an env var, falling back to *default* when it is blank."""
    return os.getenv(key, "").strip() or default


def _db_schema_from_env() -> str:
    """Read the schema the application works in.

    Only the three schemas the project owns are accepted. A typo would
    otherwise create a fourth schema at startup and hide migrations that
    never ran in the schema the deployment actually reads.
    """
    raw = os.getenv("DB_SCHEMA", "").strip() or _DEFAULT_DB_SCHEMA
    if raw not in DB_SCHEMAS:
        log.warning(
            "Invalid DB_SCHEMA '%s'; using %s. Allowed schemas: %s.",
            raw,
            _DEFAULT_DB_SCHEMA,
            ", ".join(sorted(DB_SCHEMAS)),
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

    bot_token: str = field(repr=False)
    initial_owner_id: int
    database_url: str = field(repr=False)
    community_name: str
    prefixes: tuple[str, ...]
    port: int
    bind_host: str
    main_group: int
    main_channel: int
    logs: tuple[int, int | None]
    logs_errors: tuple[int, int | None]
    proofs: tuple[int, int | None]
    appeals: tuple[int, int | None]
    album_debounce: int
    log_level: int
    modules_load: tuple[str, ...]
    modules_no_load: tuple[str, ...]
    redis_url: str | None = field(repr=False)
    db_pool_size: int
    db_max_overflow: int
    db_schema: str
    pg_cron_enabled: bool
    promotion_request_ttl_days: int
    warn_expiry_days: int
    fed_warn_limit: int
    warn_limit: int
    api_id: int
    api_hash: str = field(repr=False)
    mtproto_session: str
    sentry_dsn: str = field(repr=False)
    extra_infra_chats: tuple[int, ...]
    kurigram_workers: int

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

    def is_infrastructure_chat(self, chat_id: int | None) -> bool:
        """Check whether *chat_id* is a deployment-owned destination.

        The main group, main channel, proof archive, and the three log and
        appeal destinations are infrastructure, not managed federation
        groups. They must never be connected through the join flow, even
        when one of them is a group rather than a channel.
        """
        if chat_id is None or chat_id == 0:
            return False
        return chat_id in {
            self.main_group,
            self.main_channel,
            self.proofs[0],
            self.logs[0],
            self.logs_errors[0],
            self.appeals[0],
            *self.extra_infra_chats,
        }

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
            bind_host=_env_or("BIND_HOST", _DEFAULT_BIND_HOST),
            main_group=_main_group_from_env(),
            main_channel=_main_channel_from_env(),
            logs=parse_chat_id(os.getenv("LOGS", "").strip()),
            logs_errors=parse_chat_id(os.getenv("LOGS_ERRORS", "").strip()),
            proofs=_proofs_from_env(),
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
            pg_cron_enabled=_bool_from_env("PG_CRON_ENABLED", default=False),
            promotion_request_ttl_days=_int_from_env(
                "PROMOTION_REQUEST_TTL_DAYS",
                _DEFAULT_PROMOTION_REQUEST_TTL_DAYS,
                minimum=0,
            ),
            warn_expiry_days=_int_from_env("WARN_EXPIRY_DAYS", 0, minimum=0),
            fed_warn_limit=_int_from_env("FED_WARN_LIMIT", 0, minimum=0),
            warn_limit=_int_from_env("WARN_LIMIT", 3, minimum=1),
            api_id=_int_from_env("API_ID", 0, minimum=0),
            api_hash=os.getenv("API_HASH", "").strip(),
            mtproto_session=_env_or("MTPROTO_SESSION", "tcbot_mtproto"),
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
            extra_infra_chats=_infra_chat_ids_from_env(),
            kurigram_workers=_workers_from_env(),
        )


# * The configuration is built on first access (PEP 562) instead of at
# * import time. Importing the package must not require the bot
# * credentials: the Alembic environment, the migration generator, and
# * the test collection all import ``tcbot`` submodules without a
# * running bot. The first read still fails fast when a required
# * setting is missing, and the bot reads it while starting up.
_cfg: Configs | None = None
# * Two threads can first read ``tcbot.cfg`` before either publishes the
# * module attribute. Without a lock both build a Configs, so a direct
# * importer and the module can end up with different instances.
_cfg_lock = threading.Lock()


def __getattr__(name: str) -> Configs:
    """Return the configuration singleton, building it on first access."""
    if name != "cfg":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    global _cfg
    if _cfg is None:
        with _cfg_lock:
            if _cfg is None:
                loaded = Configs.load()
                _cfg = loaded
                # * Cache it as a real module attribute so later reads skip
                # * this hook. Publish only after the full value is built.
                globals()["cfg"] = loaded
    return _cfg


__all__ = [
    "Configs",
    "cfg",
    "parse_chat_id",
    "parse_list",
    "parse_port",
]
