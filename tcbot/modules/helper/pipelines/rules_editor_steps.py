# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared steps, limits, and authorization for the rules editor."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, cast

from tcbot import database as db
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

_TCRULES_CMDS = build_prefixed_filters("tcrules") | build_prefixed_filters("tcrls")

WAITING_EDITOR_MENU = 0
WAITING_CONFIRM_DISCARD = 5

_TITLE_MAX: int = 200
_BODY_MAX: int = 3500
_URL_MAX: int = 500
_SLUG_MAX: int = 40

_EDITOR_SCOPE_KEYS = (
    "rules_set",
    "rules_version",
    "rules_step",
    "rules_item_title",
    "rules_item_body",
    "rules_category",
    "rules_category_key",
)


async def editor_allowed(update: Update) -> bool:
    """Re-check the editor capability on every editor surface.

    A capability can be revoked while a panel or a dialog stays open, so
    every mutation re-reads the permission instead of trusting the command
    that opened the editor. A lookup failure rejects.
    """
    uid = update.effective_user.id if update.effective_user else 0
    try:
        return await db.users_roles.has_permission(uid, "rules.manage")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("rules.manage lookup failed for %d: %s", uid, exc)
        return False


def clear_item_step(scope: dict[str, Any]) -> None:
    """Forget a completed text step so a later chat message cannot repeat it."""
    for key in ("rules_step", "rules_item_title", "rules_item_body"):
        scope.pop(key, None)


def clear_editor_scope(scope: dict[str, Any]) -> None:
    """Drop every editor key so a later session starts clean."""
    for key in _EDITOR_SCOPE_KEYS:
        scope.pop(key, None)


async def refuse_editor(update: Update) -> None:
    """Answer the callback and explain why an editor action was refused."""
    query = update.callback_query
    if query is not None:
        try:
            await query.answer()
        except Exception as exc:
            log.debug("editor refusal answer failed: %s", exc)
    msg = query.message if query is not None else update.effective_message
    if msg is not None:
        await reply_rich(
            cast("Any", msg),
            replies.refuse_permission(await locale_for_update(update), plain=True),
            log_label="rules editor refusal",
            parse_mode=None,
        )


def slug(title: str) -> str:
    """Derive a stable category slug from a display title."""
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return base[:_SLUG_MAX] or "category"
