# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Immutable configuration dataclass loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from .parsing import (
    _DEFAULT_COMMUNITY_CHANNEL_URL,
    _DEFAULT_COMMUNITY_EXEC_URL,
    _DEFAULT_COMMUNITY_GROUP_URL,
    _DEFAULT_COMMUNITY_LOGS_URL,
    _DEFAULT_COMMUNITY_TRAVEL_URL,
    _DEFAULT_PORT,
    _auto_webhook_url,
    _env_list,
    _int_from_env,
    _owner_id_from_env,
    _parse_log_level,
    _required_env,
    _resolve_webhook_secret,
    _warn_bot_token_fmt,
    _warn_mongodb_uri_fmt,
    parse_chat_id,
    parse_list,
    parse_port,
)

log = logging.getLogger(__name__)


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
    appeal_discussion_topic: int
    extend_group: str
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
    community_exec_url: str
    community_travel_url: str
    api_id: int
    api_hash: str
    mtproto_session: str

    # * Properties below handle lazy type-casting from raw env strings.
    @property
    def port_int(self) -> int:
        """Parse the PORT env string into an int, falling back to 5000 on invalid values."""
        return parse_port(self.port)

    @property
    def main_group_id(self) -> int:
        """Return MAIN_GROUP as int, or 0 when unset or invalid."""
        try:
            return int(self.main_group) if self.main_group else 0
        except ValueError:
            log.warning("Invalid MAIN_GROUP '%s', defaulting to 0.", self.main_group)
            return 0

    @property
    def main_channel_id(self) -> int:
        """Return MAIN_CHANNEL as int, or 0 when unset or invalid."""
        try:
            return int(self.main_channel) if self.main_channel else 0
        except ValueError:
            log.warning(
                "Invalid MAIN_CHANNEL '%s', defaulting to 0.", self.main_channel
            )
            return 0

    @property
    def extend_group_id(self) -> int:
        """Return EXTEND_GROUP as int, or 0 when unset or invalid."""
        try:
            return int(self.extend_group) if self.extend_group else 0
        except ValueError:
            log.warning(
                "Invalid EXTEND_GROUP '%s', defaulting to 0.", self.extend_group
            )
            return 0

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
        load_dotenv(find_dotenv(env_file) or find_dotenv(".env"))

        # ! BOT_TOKEN and MONGODB_URI are strictly required for runtime startup.
        token = _required_env("BOT_TOKEN")
        _warn_bot_token_fmt(token)
        mongodb_uri = _required_env("MONGODB_URI")
        _warn_mongodb_uri_fmt(mongodb_uri)

        owner_id = _owner_id_from_env()

        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = parse_list(raw_prefixes) or ["/", "!", "."]

        db_name = os.getenv("DB_NAME", "tcbot").strip() or "tcbot"

        return Configs(
            bot_token=token,
            owner_id=owner_id,
            mongodb_uri=mongodb_uri,
            db_name=db_name,
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip() or "Bot",
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
            appeal_discussion_topic=_int_from_env(
                "APPEAL_DISCUSSION_TOPIC", 0, minimum=0
            ),
            extend_group=os.getenv("EXTEND_GROUP", "").strip(),
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
            community_logs_url=os.getenv(
                "COMMUNITY_LOGS_URL", _DEFAULT_COMMUNITY_LOGS_URL
            ).strip()
            or _DEFAULT_COMMUNITY_LOGS_URL,
            community_exec_url=os.getenv(
                "COMMUNITY_EXEC_URL", _DEFAULT_COMMUNITY_EXEC_URL
            ).strip()
            or _DEFAULT_COMMUNITY_EXEC_URL,
            community_travel_url=os.getenv(
                "COMMUNITY_TRAVEL_URL", _DEFAULT_COMMUNITY_TRAVEL_URL
            ).strip()
            or _DEFAULT_COMMUNITY_TRAVEL_URL,
            api_id=_int_from_env("API_ID", 0, minimum=0),
            api_hash=os.getenv("API_HASH", "").strip(),
            mtproto_session=os.getenv("MTPROTO_SESSION", "tcbot_mtproto").strip()
            or "tcbot_mtproto",
        )
