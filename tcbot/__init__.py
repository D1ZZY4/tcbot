# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import ast
import logging
import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv("config.env"))


# ───────────────────────── Config Parsing ───────────────────────── #

def parse_list(raw: str) -> list[str]:
    """
    * NOTE: Safely evaluates stringified lists from env. 
    * Fallback handles raw comma-separated strings.
    """
    if not raw.strip():
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed]
    except (ValueError, SyntaxError):
        pass
    items = raw.strip("[]").split(",")
    return [item.strip().strip("'\"") for item in items if item.strip()]


def parse_port(port_str: str) -> int:
    """
    * INFO: Resolve port string to int. 
    * 'auto' or empty ports are automatically redirected to default port 5000.
    """
    if not port_str or port_str.lower() == "auto":
        return 5000
    try:
        return int(port_str)
    except ValueError:
        print(f"Invalid PORT '{port_str}', defaulting to 5000.", file=sys.stderr)
        return 5000


def parse_chat_id(raw: str) -> tuple[int, int | None]:
    """
    ! WARNING: DO NOT CHANGE THE PARSING LOGIC HERE. 
    ! INCORRECT MODIFICATIONS WILL BREAK ALL TELEGRAM CHAT AND THREAD ROUTINGS SYSTEMWIDE.
    """
    if not raw:
        return 0, None
    if "/" in raw:
        chat_str, thread_str = raw.split("/", 1)
        return int(chat_str), int(thread_str)
    return int(raw), None


def _int_from_env(key: str, default: int) -> int:
    """
    ! CRITICAL: DO NOT TOUCH OR MODIFY THIS FUNCTION IF YOU DON'T KNOW WHAT YOU ARE DOING.
    ! ANY CHANGES HERE WILL AFFECT ALL INTEGER CONFIGS AND MAY CAUSE THE BOT TO CRASH ON BOOT.
    """
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
    """
    * INFO: Dynamically fetches the logging level int from the standard logging module.
    """
    level = getattr(logging, raw.strip().upper(), None)
    if isinstance(level, int):
        return level
    print(f"Invalid LOG_LEVEL '{raw}', defaulting to INFO.", file=sys.stderr)
    return logging.INFO


# ─────────────────── Immutable Config Dataclass ─────────────────── #

@dataclass(frozen=True)
class Configs:
    """
    ! WARNING: THIS DATACLASS IS FROZEN. DO NOT TEMPER WITH THE SCHEMA OR ATTRIBUTE NAMES.
    ! ANY SCHEMA CHANGES HERE MUST BE SYNCHRONIZED DIRECTLY WITH THE ADAPTER CLASS BELOW.
    """

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
    proof_timeout_seconds: int
    appeal_timeout_seconds: int
    appeal_discussion_topic: int
    extend_group: str
    album_debounce_seconds: int
    log_level: int
    modules_load: list[str]
    modules_no_load: list[str]

    # * NOTE: Properties below handle lazy type casting and formatting from raw env data.
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
        load_dotenv(find_dotenv(env_file))

        # ! ALERT: BOT_TOKEN IS STRICTLY REQUIRED! DO NOT MODIFY THIS TERMINATION LOGIC.
        # ! IF THE BOT FAILS TO LOAD THE TOKEN FROM CONFIG.ENV, IT WILL TERMINATE IMMEDIATELY.
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required but not set.")

        try:
            owner_id = int(os.getenv("OWNER_ID", "0").strip())
        except ValueError:
            owner_id = 0

        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = parse_list(raw_prefixes) or ["/"]

        # ! WARNING: ENSURE ALL ENVIRONMENT KEYS EXACTLY MATCH THE HARDCODED STRINGS BELOW.
        # ! MISMATCHED STRINGS WILL CAUSE THE VALUES TO RESOLVE TO DEFAULT OR EMPTY EMITTED DATA.
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


class _CfgAdapter:
    """
    * INFO: Thin adapter so modules can write `cfg.logs`, `cfg.main_group`, etc.
    ! WARNING: Changing properties here will break code synchronization across external modules.
    """

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


# * NOTE: This adapter instance 'cfg' is globally shared across all modules.
# ! ALERT: DO NOT CHANGE THE INSTANTIATION VARIABLE NAME TO PREVENT BREAKING INTEGRATIONS.
cfg = _CfgAdapter(configs)
