# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Resolve-target helpers that reply with the spec-locked failure copy."""
from __future__ import annotations

from typing import Any, Optional

from telegram import Update
from telegram.ext import ContextTypes

from ...modules.messages import M
from ...utils.targets import ResolvedTarget, get_reason
from ...utils.targets import resolve_target as _resolve_target


async def resolve_or_complain(
    update: Update, context: ContextTypes.DEFAULT_TYPE, msg: Any
) -> Optional[ResolvedTarget]:
    """Return the resolved target or reply ``"Cannot resolve user."`` and ``None``."""
    target = await _resolve_target(update, context)
    if target is None:
        await msg.reply_text(M.CANNOT_RESOLVE_USER)
    return target


def reason_from_args(
    context: ContextTypes.DEFAULT_TYPE, update: Update
) -> str:
    """Re-export :func:`tgbot_tcf.utils.targets.get_reason` for handler use."""
    return get_reason(context, update)
