# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute/unmute executor + conversation factory."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.workflows.muting_flow.duration import (
    _DAYS_PER_YEAR,
    _DURATION_RE,
    _MAX_DURATION_DAYS,
    _SECS_PER_DAY,
    _SECS_PER_HOUR,
    fmt_duration,
    parse_duration,
)
from tcbot.modules.helper.workflows.muting_flow.factory import (
    _exec_mute,
    mute_conversation,
)
from tcbot.modules.helper.workflows.muting_flow.mute import _execute_mute
from tcbot.modules.helper.workflows.muting_flow.shared import proof, reason
from tcbot.modules.helper.workflows.muting_flow.unmute import execute_unmute
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

__all__ = [
    "_DAYS_PER_YEAR",
    "_DURATION_RE",
    "_MAX_DURATION_DAYS",
    "_SECS_PER_DAY",
    "_SECS_PER_HOUR",
    "_exec_mute",
    "_execute_mute",
    "cfg",
    "execute_unmute",
    "fmt_duration",
    "locale_for_update",
    "log",
    "mute_conversation",
    "parse_duration",
    "proof",
    "reason",
]
