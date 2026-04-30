# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Multi-prefix command dispatcher.

Telegram's CommandHandler only matches the `/` prefix. The TCF spec requires
that every command also work with `.` and `!` prefixes (e.g. `/cban`,
`.cban`, `!cban` all behave identically).

This module exposes:
- `register_command(name, callback)` to associate a command name with its
  callback. Call this for every alias.
- `dispatch_alt_prefix(update, context)` — a single MessageHandler callback
  that parses messages starting with `.` or `!`, populates `context.args`,
  and forwards to the right callback.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_REGISTRY: dict[str, _Handler] = {}

_ALT_RE = re.compile(
    r"^[.!]([A-Za-z][A-Za-z0-9_]*)(?:@[A-Za-z0-9_]+)?(?:[ \t]+([\s\S]*))?$"
)


def register_command(name: str, callback: _Handler) -> None:
    _REGISTRY[name.lower()] = callback


async def dispatch_alt_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    m = _ALT_RE.match(msg.text)
    if not m:
        return
    cmd = m.group(1).lower()
    rest = (m.group(2) or "").strip()
    cb = _REGISTRY.get(cmd)
    if cb is None:
        return
    context.args = rest.split() if rest else []
    try:
        await cb(update, context)
    except Exception:  # noqa: BLE001
        logger.exception("Alt-prefix dispatch failed for %s", cmd)
