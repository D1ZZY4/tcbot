# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared constants and small helpers for the /check profile views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Bot

from tcbot import database as db
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.keyboards import check_back_row
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import date_or_unknown

if TYPE_CHECKING:
    from telegram import InlineKeyboardButton

log = get_logger(__name__)

_PAGE_SIZE = 5
_REASON_PREVIEW_LEN = 80
_BAN_LIST_REASON_LEN = 60
_BTNS_PER_ROW = 3


async def _resolve_user_info(bot: Bot, target_id: int) -> tuple[str, str | None]:
    """Return (display_name, username_or_None) instantly from cache.

    Stale-while-revalidate: the profile renders with zero added latency
    while a background sync refreshes the stored identity for the next
    view. Thin wrapper kept so the profile gather below keeps its shape.
    """
    try:
        doc = await db.users_cache.get_user(target_id)
    except Exception as exc:
        log.debug("_resolve_user_info cache read failed for %d: %s", target_id, exc)
        doc = None
    if doc:
        fname = doc.get("first_name") or str(target_id)
        uname = doc.get("username") or None
    else:
        fname, uname = str(target_id), None
    if identity_needs_refresh(doc):
        launch_identity_refresh(bot, target_id)
    return fname, uname


def _back_to_check(
    target_id: int, locale: str | None = None
) -> list[InlineKeyboardButton]:
    """Back row to the /check profile (single source: keyboards)."""
    return check_back_row(target_id, locale)


def _maybe_caveat(text: str, locale: str | None, *, failed: bool) -> str:
    """Append the shared incomplete-counters note when a count read failed."""
    if failed:
        text += f"\n\n{t('checking.profile.caveat', locale)}"
    return text


async def _name(uid: int) -> str:
    """Fast cache-only name lookup; falls back to numeric ID string."""
    return await db.users_cache.get_first_name(uid, str(uid))


async def _async_const(value: Any) -> Any:
    """Wrap a constant in an async coroutine so gather() can mix it with awaits."""
    return value


def _ban_ts(ban: dict[str, Any], locale: str | None = None) -> str:
    return date_or_unknown(ban.get("timestamp"), locale)


def _appeal_ts(ban: dict[str, Any], locale: str | None = None) -> str:
    return date_or_unknown(
        ban.get("appeal_submitted_at") or ban.get("timestamp"), locale
    )
