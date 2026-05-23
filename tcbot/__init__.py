# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Configuration singleton – loads env vars into a frozen dataclass and exposes a thin ``cfg`` adapter."""

from __future__ import annotations

import ast
import logging
import os
import sys
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv("config.env"))


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
    """Resolve a port string to an integer; ``'auto'`` or empty strings default to 5000."""
    if not port_str or port_str.lower() == "auto":
        return 5000
    try:
        return int(port_str)
    except ValueError:
        print(f"Invalid PORT '{port_str}', defaulting to 5000.", file=sys.stderr)
        return 5000


def parse_chat_id(raw: str) -> tuple[int, int | None]:
    """Parse a ``CHAT_ID`` or ``CHAT_ID/THREAD_ID`` env string into ``(chat_id, thread_id | None)``."""
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
        raise RuntimeError("OWNER_ID is required and must be a positive integer.")
    try:
        owner_id = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(
            "OWNER_ID is required and must be a positive integer."
        ) from exc
    if owner_id <= 0:
        raise RuntimeError("OWNER_ID is required and must be a positive integer.")
    return owner_id


def _int_from_env(key: str, default: int) -> int:
    """Read an integer env var, returning ``default`` on parse error."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        print(f"Invalid integer for {key}, using {default}.", file=sys.stderr)
        return default


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
    print(f"Invalid LOG_LEVEL '{raw}', defaulting to INFO.", file=sys.stderr)
    return logging.INFO


# ─────────────────── Immutable Config Dataclass ─────────────────── #


@dataclass(frozen=True)
class Configs:
    """Immutable configuration dataclass – all fields are loaded from environment variables."""

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
        return parse_port(self.port)

    @property
    def main_group_id(self) -> int:
        return int(self.main_group) if self.main_group else 0

    @property
    def main_channel_id(self) -> int:
        return int(self.main_channel) if self.main_channel else 0

    @property
    def extend_group_id(self) -> int:
        return int(self.extend_group) if self.extend_group else 0

    @property
    def logs_tuple(self) -> tuple[int, int | None]:
        return parse_chat_id(self.logs)

    @property
    def proofs_id(self) -> tuple[int, int | None]:
        return parse_chat_id(self.proofs)

    @property
    def logs_errors_id(self) -> tuple[int, int | None]:
        return parse_chat_id(self.logs_errors)

    @property
    def appeals_id(self) -> tuple[int, int | None]:
        return parse_chat_id(self.appeals)

    @staticmethod
    def load(env_file: str = "config.env") -> "Configs":
        """Load all configuration from environment variables and return a ``Configs`` instance."""
        load_dotenv(find_dotenv(env_file))

        # ! BOT_TOKEN is strictly required; the bot cannot start without it.
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required but not set.")

        owner_id = _owner_id_from_env()

        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = parse_list(raw_prefixes) or ["/"]

        return Configs(
            bot_token=token,
            owner_id=owner_id,
            mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
            db_name=os.getenv("DB_NAME", "tcbot").strip(),
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip(),
            prefixes=prefixes,
            port=os.getenv("PORT", "5000").strip(),
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
            proof_timeout_seconds=_int_from_env("PROOF_TIMEOUT_SECONDS", 100),
            appeal_timeout_seconds=_int_from_env("APPEAL_TIMEOUT_SECONDS", 600),
            appeal_discussion_topic=_int_from_env("APPEAL_DISCUSSION_TOPIC", 0),
            extend_group=os.getenv("EXTEND_GROUP", "").strip(),
            album_debounce_seconds=_int_from_env("ALBUM_DEBOUNCE_SECONDS", 2),
            log_level=_parse_log_level(os.getenv("LOG_LEVEL", "INFO")),
            modules_load=_env_list("MODULES_LOAD"),
            modules_no_load=_env_list("MODULES_NO_LOAD"),
        )


configs = Configs.load()


# ! Property names in _CfgAdapter are imported by every module — rename with caution.
class _CfgAdapter:
    """Thin adapter that exposes ``Configs`` fields with the short canonical names used by all modules."""

    def __init__(self, c: Configs) -> None:
        self._c = c

    @property
    def bot_token(self) -> str:
        return self._c.bot_token

    @property
    def initial_owner_id(self) -> int:
        return self._c.owner_id

    @property
    def community_name(self) -> str:
        return self._c.community_name

    @property
    def mongodb_uri(self) -> str:
        return self._c.mongodb_uri

    @property
    def db_name(self) -> str:
        return self._c.db_name

    @property
    def prefixes(self) -> list[str]:
        return self._c.prefixes

    @property
    def port(self) -> int:
        return self._c.port_int

    @property
    def main_group(self) -> int:
        return self._c.main_group_id

    @property
    def main_channel(self) -> int:
        return self._c.main_channel_id

    @property
    def exec_group(self) -> int:
        return self._c.extend_group_id

    @property
    def logs(self) -> tuple[int, int | None]:
        return self._c.logs_tuple

    @property
    def logs_errors(self) -> tuple[int, int | None]:
        return self._c.logs_errors_id

    @property
    def proofs(self) -> tuple[int, int | None]:
        return self._c.proofs_id

    @property
    def appeals(self) -> tuple[int, int | None]:
        return self._c.appeals_id

    @property
    def appeal_log_handle(self) -> str:
        return self._c.appeal_log_handle

    @property
    def proof_timeout(self) -> int:
        return self._c.proof_timeout_seconds

    @property
    def appeal_timeout(self) -> int:
        return self._c.appeal_timeout_seconds

    @property
    def appeal_discussion_topic(self) -> int:
        return self._c.appeal_discussion_topic

    @property
    def album_debounce(self) -> int:
        return self._c.album_debounce_seconds

    @property
    def log_level(self) -> int:
        return self._c.log_level

    @property
    def modules_load(self) -> list[str]:
        return self._c.modules_load

    @property
    def modules_no_load(self) -> list[str]:
        return self._c.modules_no_load


# * This adapter instance is the single global 'cfg' used by every module.
cfg = _CfgAdapter(configs)
