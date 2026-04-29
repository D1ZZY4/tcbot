# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Thin Telegram-update handlers for the Transsion Core Federation bot.

Each module in this package is a small, focused entry point: it parses the
incoming :class:`telegram.Update`, performs the spec-mandated validation,
delegates the actual work to the matching submodule of
:mod:`tgbot_tcf.modules`, and then sends the right reply or log entry
using the centralised copy in :mod:`tgbot_tcf.modules.messages`.

Per-request helpers (auth guards, target resolution, safe Telegram
wrappers, cross-group enforcement) live in :mod:`.helper`.
"""
from . import (
    admins,
    affiliate,
    appeal,
    ban,
    broadcast,
    checks,
    helper,
    help as help_h,
    links,
    lists,
    maintenance,
    membercache,
    menu,
    welcome,
)

__all__ = [
    "admins",
    "affiliate",
    "appeal",
    "ban",
    "broadcast",
    "checks",
    "helper",
    "help_h",
    "links",
    "lists",
    "maintenance",
    "membercache",
    "menu",
    "welcome",
]
