# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Centralised configuration object used across all modules."""
from __future__ import annotations

import ast
import os
import socket
from dataclasses import dataclass
from typing import Optional, Tuple

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv("config.env"))


def _parse_list(raw: str) -> list[str]:
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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _parse_port(port_str: str) -> int:
    if not port_str or port_str.lower() == "auto":
        return 5000
    try:
        return int(port_str)
    except ValueError:
        return 5000


def _parse_chat_id(raw: str) -> Tuple[int, Optional[int]]:
    if not raw:
        return 0, None
    if "/" in raw:
        chat_str, thread_str = raw.split("/", 1)
        return int(chat_str), int(thread_str)
    return int(raw), None


def _int_from_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_list(key: str) -> list[str]:
    raw = os.getenv(key, "").strip()
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


@dataclass(frozen=True)
class Config:
    bot_token: str
    initial_owner_id: int
    mongodb_uri: str
    db_name: str
    community_name: str
    prefixes: list[str]
    _port: int
    main_group: int
    main_channel: int
    exec_group: int
    _proofs: Tuple[int, Optional[int]]
    _logs: Tuple[int, Optional[int]]
    _logs_errors: Tuple[int, Optional[int]]
    _appeals: Tuple[int, Optional[int]]
    proof_timeout: int
    appeal_timeout: int
    album_debounce: int
    modules_load: list[str]
    modules_no_load: list[str]

    @property
    def port(self) -> int:
        return self._port

    @property
    def proofs(self) -> Tuple[int, Optional[int]]:
        return self._proofs

    @property
    def logs(self) -> Tuple[int, Optional[int]]:
        return self._logs

    @property
    def logs_errors(self) -> Tuple[int, Optional[int]]:
        return self._logs_errors

    @property
    def appeals(self) -> Tuple[int, Optional[int]]:
        return self._appeals

    @staticmethod
    def load() -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required but not set.")

        owner_str = os.getenv("OWNER_ID", "0").strip()
        try:
            owner_id = int(owner_str)
        except ValueError:
            owner_id = 0

        raw_prefixes = os.getenv("PREFIXES", '["/", "!", "."]')
        prefixes = _parse_list(raw_prefixes) or ["/"]

        port = _parse_port(os.getenv("PORT", "5000").strip())

        main_group_raw = os.getenv("MAIN_GROUP", "0").strip()
        try:
            main_group = int(main_group_raw)
        except ValueError:
            main_group = 0

        main_channel_raw = os.getenv("MAIN_CHANNEL", "0").strip()
        try:
            main_channel = int(main_channel_raw)
        except ValueError:
            main_channel = 0

        extend_group_raw = os.getenv("EXTEND_GROUP", "0").strip()
        try:
            exec_group = int(extend_group_raw) if extend_group_raw else 0
        except ValueError:
            exec_group = 0

        return Config(
            bot_token=token,
            initial_owner_id=owner_id,
            mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
            db_name=os.getenv("DB_NAME", "tcbot").strip(),
            community_name=os.getenv("COMMUNITY_NAME", "Bot").strip(),
            prefixes=prefixes,
            _port=port,
            main_group=main_group,
            main_channel=main_channel,
            exec_group=exec_group,
            _proofs=_parse_chat_id(os.getenv("PROOFS", "").strip()),
            _logs=_parse_chat_id(os.getenv("LOGS", "").strip()),
            _logs_errors=_parse_chat_id(os.getenv("LOGS_ERRORS", "").strip()),
            _appeals=_parse_chat_id(os.getenv("APPEALS", "").strip()),
            proof_timeout=_int_from_env("PROOF_TIMEOUT_SECONDS", 100),
            appeal_timeout=_int_from_env("APPEAL_TIMEOUT_SECONDS", 600),
            album_debounce=_int_from_env("ALBUM_DEBOUNCE_SECONDS", 2),
            modules_load=_env_list("MODULES_LOAD"),
            modules_no_load=_env_list("MODULES_NO_LOAD"),
        )


cfg = Config.load()
