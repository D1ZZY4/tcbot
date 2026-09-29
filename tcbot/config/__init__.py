# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configuration package: env parsing, immutable models, and the cfg adapter."""

from __future__ import annotations

from .adapter import _CfgAdapter
from .models import Configs
from .parsing import (
    _DEFAULT_COMMUNITY_CHANNEL_URL,
    _DEFAULT_COMMUNITY_EXEC_URL,
    _DEFAULT_COMMUNITY_GROUP_URL,
    _DEFAULT_COMMUNITY_LOGS_URL,
    _DEFAULT_COMMUNITY_TRAVEL_URL,
    _DEFAULT_PORT,
    _ERR_OWNER_ID,
    _REPLIT_DEV_DOMAIN_VAR,
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

__all__ = [
    "_DEFAULT_COMMUNITY_CHANNEL_URL",
    "_DEFAULT_COMMUNITY_EXEC_URL",
    "_DEFAULT_COMMUNITY_GROUP_URL",
    "_DEFAULT_COMMUNITY_LOGS_URL",
    "_DEFAULT_COMMUNITY_TRAVEL_URL",
    "_DEFAULT_PORT",
    "_ERR_OWNER_ID",
    "_REPLIT_DEV_DOMAIN_VAR",
    "Configs",
    "_CfgAdapter",
    "_auto_webhook_url",
    "_env_list",
    "_int_from_env",
    "_owner_id_from_env",
    "_parse_log_level",
    "_required_env",
    "_resolve_webhook_secret",
    "_warn_bot_token_fmt",
    "_warn_mongodb_uri_fmt",
    "parse_chat_id",
    "parse_list",
    "parse_port",
]
