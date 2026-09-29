# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Paginated /check ban and appeal drill-downs plus their shared renderer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.keyboards import (
    back_to_module_kb,
    detail_kb,
    paged_drill_kb,
)

# * Name lookups resolve through the package namespace, keeping one live
# * binding for every caller (mirrors ban_flow's _flow pattern).
from tcbot.modules.helper.workflows import check_flow as _flow
from tcbot.modules.helper.workflows.check_flow.shared import (
    _BAN_LIST_REASON_LEN,
    _BTNS_PER_ROW,
    _PAGE_SIZE,
    _appeal_ts,
    _back_to_check,
    _ban_ts,
    _maybe_caveat,
    log,
)
from tcbot.utils.formatter import code, italic, user_ref
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class CheckBansMixin:
    """Ban and appeal drill-down builders for the /check command."""

    @classmethod
    async def bans_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban (active+inactive) with detail buttons per item."""
        return await _ban_list_render(
            target_id,
            page,
            locale,
            db_call=db.bans_db.user_bans,
            count_call=db.bans_db.user_ban_count,
            key_prefix="bans",
            nav_prefix="check_bans",
            active_key="active",
            inactive_key="inactive",
            ts=_ban_ts,
            show_reason=True,
        )

    @classmethod
    async def ban_detail(
        cls,
        target_id: int,
        ban_id: str,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Show a single ban's full detail (text + optional Proof button)."""
        try:
            ban = await db.bans_db.get_ban(ban_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # * Transient DB failure: show a retry card that is visibly
            # * different from the genuine not-found card, so a moderator
            # * never mistakes an outage for a clean record.
            text = t(
                "checking.bans.db_fail",
                locale,
                ban=Safe(code(ban_id)),
            )
            return text, back_to_module_kb(f"check_bans:{target_id}:0", locale)
        if not ban or ban.get("banned_user_id") != target_id:
            text = t(
                "checking.bans.not_found",
                locale,
                ban=Safe(code(ban_id)),
            )
            return text, back_to_module_kb(f"check_bans:{target_id}:0", locale)

        text, proof_link = await build_ban_detail(ban, locale=locale)
        return text, detail_kb(
            back_callback=f"check_bans:{target_id}:0",
            proof_link=proof_link,
            appeal_link=ban.get("appeal_link"),
            locale=locale,
        )

    @classmethod
    async def appeals_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban that ever had an appeal submitted."""
        # * Server-side appeal filter (sparse index): only appealable rows
        # * travel over the wire instead of the user's full ban history.
        return await _ban_list_render(
            target_id,
            page,
            locale,
            db_call=db.bans_db.user_appealable_bans,
            count_call=db.bans_db.user_appeal_count,
            key_prefix="appeals_list",
            nav_prefix="check_appeals",
            active_key="pending",
            inactive_key="approved",
            ts=_appeal_ts,
        )


async def _ban_list_render(
    target_id: int,
    page: int,
    locale: str | None,
    *,
    db_call: Callable[..., Awaitable[list[Any]]],
    count_call: Callable[[int], Awaitable[int]],
    key_prefix: str,
    nav_prefix: str,
    active_key: str,
    inactive_key: str,
    ts: Callable[..., str],
    show_reason: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared paginated ban/appeal list renderer (index + detail buttons).

    Fetches only ``_PAGE_SIZE`` rows plus the real total per page turn,
    and keeps the header count exact even when a page tap comes in out of
    range (page is clamped before the slice is requested).
    """
    total, display_name = await asyncio.gather(
        count_call(target_id),
        _flow._name(target_id),
        return_exceptions=True,
    )
    if isinstance(display_name, BaseException):
        display_name = str(target_id)
    if isinstance(total, BaseException) or not isinstance(total, int):
        total = 0
        count_failed = True
    else:
        count_failed = False
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    try:
        chunk = await db_call(target_id, skip=page * _PAGE_SIZE, limit=_PAGE_SIZE)
        chunk_failed = False
    except Exception:
        log.exception("check_flow %s list fetch failed for %d", key_prefix, target_id)
        chunk = []
        chunk_failed = True
    if count_failed:
        # * Honest fallback when the count itself fails: show the fetched page.
        total = len(chunk)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    if not chunk:
        if count_failed or chunk_failed:
            text = t("checking.warns.db_fail", locale)
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])
        text = t(
            f"checking.{key_prefix}.empty",
            locale,
            user=Safe(user_ref(target_id, display_name)),
        )
        return _maybe_caveat(text, locale, failed=count_failed), InlineKeyboardMarkup(
            [_back_to_check(target_id, locale)]
        )

    lines = [
        t(
            f"checking.{key_prefix}.header",
            locale,
            n=total,
            page=page + 1,
            pages=total_pages,
        )
        + "\n"
    ]
    items: list[tuple[str, str]] = []
    base_idx = page * _PAGE_SIZE
    for i, ban in enumerate(chunk, start=1):
        status_key = active_key if ban.get("is_active") else inactive_key
        status = t(f"checking.{key_prefix}.{status_key}", locale)
        item_kwargs: dict[str, Any] = {
            "i": base_idx + i,
            "status": Safe(status),
            "ban": Safe(code(ban.get("ban_id", ""))),
            "ts": Safe(ts(ban, locale)),
        }
        if show_reason:
            stored_reason = ban.get("reason", None)
            reason_short = str(
                stored_reason
                if stored_reason is not None
                else t("checking.events.no_reason", locale, plain=True)
            )[:_BAN_LIST_REASON_LEN]
            item_kwargs["reason"] = Safe(italic(reason_short))
        lines.append(t(f"checking.{key_prefix}.item", locale, **item_kwargs))
        items.append(
            (
                str(base_idx + i),
                f"check_ban_item:{target_id}:{ban.get('ban_id', '')}",
            )
        )

    return _maybe_caveat(
        "\n".join(lines), locale, failed=count_failed or chunk_failed
    ), paged_drill_kb(
        items,
        page=page,
        total_pages=total_pages,
        nav_prefix=f"{nav_prefix}:{target_id}",
        back_callback=f"check_main:{target_id}",
        per_row=_BTNS_PER_ROW,
        locale=locale,
    )
