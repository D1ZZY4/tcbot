# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Comprehensive user-profile view for /check: bans, warns, kicks, mutes, appeals."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from telegram import Bot, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.identity import Identity, classify, profile_note
from tcbot.modules.helper.keyboards import (
    back_to_module_kb,
    check_back_row,
    check_profile_kb,
    check_warn_groups_kb,
    check_warns_back_row,
    detail_kb,
    paged_drill_kb,
)
from tcbot.utils.formatter import bold, code, italic, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.pagination import date_or_unknown, nav_row
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from telegram import InlineKeyboardButton

log = logging.getLogger(__name__)

_PAGE_SIZE = 5
_REASON_PREVIEW_LEN = 80
_BAN_LIST_REASON_LEN = 60
_BTNS_PER_ROW = 3


# ────────────────────────── Small helpers ───────────────────────── #


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


# ─────────────────────────── Check class ────────────────────────── #


class Check:
    """All view builders for the /check user-profile command."""

    # ── Main profile ──────────────────────────────────────────────────────

    @classmethod
    async def profile(
        cls,
        bot: Bot,
        target_id: int,
        *,
        executor_id: int | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build the top-level profile view: identity + counts + drill-down keyboard.

        When ``executor_id`` is given, the target is also classified relative
        to the viewer so special identities get a recognition note (this bot,
        self, Telegram, anonymous admin); staff and Founder are already
        identified by the Role line.
        """
        # * All reads are independent; fire them in parallel for a single round-trip.
        # * return_exceptions=True prevents a single DB failure from crashing the whole view.
        # * fed_warn_total gives the federation-wide aggregate that user_total_warns hides
        # * (user_total_warns counts all historical warn docs; fed_warn_total sums active
        # * counters from warn_counts across all chats and is the staff-relevant number).
        # * The classify read is joined only when the viewer is known; /check is
        # * read-only and public, so a failed lookup degrades to no note (the
        # * fail-open "user" kind) instead of failing the whole card.
        _reads: list[Any] = [
            _resolve_user_info(bot, target_id),
            db.users_roles.role_meta(target_id),
            db.bans_db.get_active_ban(target_id),
            db.mutes_db.get_active_mute(target_id),
            db.bans_db.user_ban_count(target_id),
            db.bans_db.user_appeal_count(target_id),
            db.warns_db.user_total_warns(target_id),
            db.warns_db.user_warn_groups(target_id),
            db.warns_db.federation_warn_count(target_id),
            db.kicks_db.user_kick_count(target_id),
            db.mutes_db.user_mute_count(target_id),
        ]
        if executor_id is not None:
            _reads.append(classify(bot, executor_id, target_id))
        _results = await asyncio.gather(*_reads, return_exceptions=True)
        r_user_info = _results[0]
        r_role_meta = _results[1]
        ban_failed = isinstance(_results[2], BaseException)
        mute_failed = isinstance(_results[3], BaseException)
        counts_failed = any(isinstance(r, BaseException) for r in _results[4:11])
        active_ban = _results[2] if not ban_failed else None
        active_mute = _results[3] if not mute_failed else None
        ban_total = _results[4] if not isinstance(_results[4], BaseException) else 0
        appeal_total = _results[5] if not isinstance(_results[5], BaseException) else 0
        warn_total = _results[6] if not isinstance(_results[6], BaseException) else 0
        _wg = _results[7] if not isinstance(_results[7], BaseException) else None
        warn_groups: list[tuple[int, int]] = (
            cast("list[tuple[int, int]]", _wg) if _wg is not None else []
        )
        fed_warn_total = (
            _results[8] if not isinstance(_results[8], BaseException) else 0
        )
        kick_total = _results[9] if not isinstance(_results[9], BaseException) else 0
        mute_total = _results[10] if not isinstance(_results[10], BaseException) else 0

        if isinstance(r_user_info, BaseException):
            log.error("_resolve_user_info failed for %d: %s", target_id, r_user_info)
            fname, uname = str(target_id), None
        else:
            fname, uname = cast("tuple[str, str | None]", r_user_info)
        if isinstance(r_role_meta, BaseException):
            log.error("role_meta failed for %d: %s", target_id, r_role_meta)
            role, role_by_id, role_at = None, None, None
        else:
            role, role_by_id, role_at = cast(
                "tuple[str | None, int | None, datetime | None]", r_role_meta
            )

        # * Recognition note for special identities, owned by
        # * identity.profile_note (single source for "who is this?" copy).
        # * Staff and Founder need none: the Role line below already labels
        # * them. Cancellation propagates; any other lookup failure degrades
        # * to no note.
        identity_note: str | None = None
        if len(_results) > 11:
            r_ident = _results[11]
            if isinstance(r_ident, asyncio.CancelledError):
                raise r_ident
            if not isinstance(r_ident, BaseException):
                identity_note = profile_note(cast("Identity", r_ident), locale)

        role_label = (
            db.users_roles.ROLE_LABEL.get(
                role or "", t("checking.profile.regular", locale)
            )
            if role
            else t("checking.profile.regular", locale)
        )
        uname_part = (
            t("checking.profile.username", locale, name=uname or "")
            if uname
            else t("checking.profile.username_none", locale)
        )
        active_ban_doc = cast("BanDoc | None", active_ban)
        # * Never render a clean bill of health from a failed read: during a
        # * DB outage the lookups above coerce to None/0, which would show
        # * "Active Ban: No" and zero counts for a banned user. Surface
        # * Unknown instead so operators retry rather than trust the card.
        if ban_failed:
            active_part = t("checking.profile.unknown", locale)
        elif active_ban_doc:
            active_part = t(
                "checking.profile.yes_ban",
                locale,
                ban=Safe(
                    code(
                        active_ban_doc.get("ban_id", "")
                        if isinstance(active_ban_doc, dict)
                        else ""
                    )
                ),
            )
        else:
            active_part = t("checking.profile.no", locale)
        if mute_failed:
            active_mute_part = t("checking.profile.unknown", locale)
        else:
            active_mute_part = (
                t("checking.profile.yes", locale)
                if active_mute
                else t("checking.profile.no", locale)
            )

        # * Build the rich role line with assignment metadata where available.
        role_lines = [t("checking.profile.role", locale, role=Safe(bold(role_label)))]
        if role and role != "founder" and role_by_id:
            by_name = await db.users_cache.get_first_name(role_by_id, str(role_by_id))
            role_lines.append(
                t(
                    "checking.profile.assigned_by",
                    locale,
                    by=Safe(user_ref(role_by_id, by_name)),
                )
            )
        if role and role != "founder" and role_at:
            role_lines.append(
                t("checking.profile.assigned_at", locale, at=Safe(fmt_dt(role_at)))
            )
        role_block = Safe("\n".join(role_lines))

        uname_line = Safe(uname_part)
        active_ban_line = Safe(
            t("checking.profile.active_ban", locale, state=Safe(active_part))
        )
        active_mute_line = Safe(
            t("checking.profile.active_mute", locale, state=Safe(active_mute_part))
        )
        text = (
            (f"{identity_note}\n\n" if identity_note else "")
            + f"{t('checking.profile.title', locale)}\n\n"
            + f"{t('checking.profile.name', locale, user=Safe(user_ref(target_id, fname)))}\n"
            + f"{t('checking.profile.id', locale, id=Safe(code(str(target_id))))}\n"
            + f"{uname_line}\n"
            + f"{role_block}\n\n"
            + f"{t('checking.profile.activity', locale)}\n\n"
            + f"{active_ban_line}\n"
            + f"{active_mute_line}\n"
            + f"{t('checking.profile.total_bans', locale, n=ban_total)}\n"
            + f"{t('checking.profile.warnings', locale, active=fed_warn_total, groups=len(warn_groups) if warn_groups is not None else 0, total=warn_total)}\n"
            + f"{t('checking.profile.kicks', locale, n=kick_total)}\n"
            + f"{t('checking.profile.mutes', locale, n=mute_total)}\n"
            + f"{t('checking.profile.appeals', locale, n=appeal_total)}"
        )
        if counts_failed:
            text += f"\n\n{t('checking.profile.caveat', locale)}"

        return text, check_profile_kb(
            target_id,
            ban_total=ban_total,
            appeal_total=appeal_total,
            fed_warn_total=fed_warn_total,
            kick_total=kick_total,
            mute_total=mute_total,
            locale=locale,
        )

    # ── Bans drill-down ───────────────────────────────────────────────────

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

    # ── Warnings drill-down ───────────────────────────────────────────────

    @classmethod
    async def warns_by_group(
        cls,
        target_id: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """List groups where the user has warnings + count per group + drill-in buttons."""
        groups, display_name = await asyncio.gather(
            db.warns_db.user_warn_groups(target_id),
            _name(target_id),
            return_exceptions=True,
        )
        if isinstance(groups, BaseException):
            # * Transient DB failure: a retry card, never the empty card. An
            # * outage is not evidence the user is clean.
            text = t("checking.warns.db_fail", locale)
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        if not groups:
            text = t(
                "checking.warns.empty",
                locale,
                user=Safe(user_ref(target_id, display_name)),
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

        try:
            titles = await db.groups_db.get_group_titles([cid for cid, _ in groups])
        except Exception:
            # * Degrade to numeric chat IDs on a transient failure; the empty
            # * row list still renders, mirroring warns_in_group's {} fallback.
            titles = {}
        total = sum(c for _, c in groups)

        lines = [
            t(
                "checking.warns.header",
                locale,
                n=total,
                groups=len(groups),
            )
            + "\n"
        ]
        warn_groups: list[tuple[str, int, int]] = []
        for cid, count in groups:
            title = titles.get(cid) or str(cid)
            lines.append(
                t(
                    "checking.warns.group_line",
                    locale,
                    title=title,
                    n=Safe(bold(str(count))),
                )
            )
            warn_groups.append((title, count, cid))

        return "\n".join(lines), check_warn_groups_kb(
            target_id, warn_groups, locale=locale
        )

    @classmethod
    async def warns_in_group(
        cls,
        target_id: int,
        chat_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of individual warnings inside one chat."""
        count, titles = await asyncio.gather(
            db.warns_db.warn_count(target_id, chat_id),
            db.groups_db.get_group_titles([chat_id]),
            return_exceptions=True,
        )
        if isinstance(titles, BaseException):
            titles = {}
        if isinstance(count, BaseException) or not isinstance(count, int):
            count = 0
            count_failed = True
        else:
            count_failed = False
        total_pages = max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        try:
            warns = await db.warns_db.get_warns(
                target_id, chat_id, skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
            )
            warns_failed = False
        except Exception:
            log.exception(
                "check_flow warns_in_group fetch failed for %d/%d", target_id, chat_id
            )
            warns = []
            warns_failed = True
        if count_failed:
            # * Honest fallback when the count itself fails: show the fetched page.
            count = len(warns)
            total_pages = max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        # * get_warns is oldest-first; reverse to newest-first for consistency
        warns = list(reversed(warns))
        title = titles.get(chat_id) or str(chat_id)

        if not warns:
            text = t("checking.warns.in_empty", locale, title=title)
            rows = [check_warns_back_row(target_id, locale)]
            return _maybe_caveat(
                text, locale, failed=count_failed or warns_failed
            ), InlineKeyboardMarkup(rows)

        # * Resolve admin names with batch query
        admin_ids = [w.get("admin_id", 0) for w in warns if w.get("admin_id")]
        admin_name_map = (
            await db.users_cache.get_first_names_batch(admin_ids) if admin_ids else {}
        )

        lines = [
            t(
                "checking.warns.in_header",
                locale,
                title=title,
                n=count,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, w in enumerate(warns, start=1):
            ts = date_or_unknown(w.get("timestamp"))
            stored_reason = w.get("reason", None)
            reason_short = str(
                stored_reason
                if stored_reason is not None
                else t("checking.events.no_reason", locale, plain=True)
            )[:_REASON_PREVIEW_LEN]
            admin_id = w.get("admin_id", 0)
            admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
            lines.append(
                t(
                    "checking.warns.in_item",
                    locale,
                    i=base_idx + i,
                    ts=Safe(ts),
                    reason=Safe(italic(reason_short)),
                    admin=Safe(user_ref(admin_id, admin_name)),
                )
            )

        rows = []
        nav = nav_row(
            page, total_pages, f"check_warn_chat:{target_id}:{chat_id}", locale
        )
        if nav:
            rows.append(nav)
        rows.append(check_warns_back_row(target_id, locale))
        return _maybe_caveat(
            "\n".join(lines), locale, failed=count_failed
        ), InlineKeyboardMarkup(rows)

    # ── Kicks drill-down ──────────────────────────────────────────────────

    @classmethod
    async def kicks_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every kick record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Kicks",
            db_call=db.kicks_db.user_kicks,
            count_call=db.kicks_db.user_kick_count,
            cb_prefix=f"check_kicks:{target_id}",
            locale=locale,
        )

    # ── Mutes drill-down ──────────────────────────────────────────────────

    @classmethod
    async def mutes_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every mute record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Mutes",
            db_call=db.mutes_db.user_mutes,
            count_call=db.mutes_db.user_mute_count,
            cb_prefix=f"check_mutes:{target_id}",
            locale=locale,
        )

    # ── Appeals drill-down ────────────────────────────────────────────────

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


# ─────────────────────── Shared list helper ─────────────────────── #


def _ban_ts(ban: dict[str, Any]) -> str:
    return date_or_unknown(ban.get("timestamp"))


def _appeal_ts(ban: dict[str, Any]) -> str:
    return date_or_unknown(ban.get("appeal_submitted_at") or ban.get("timestamp"))


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
    ts: Callable[[dict[str, Any]], str],
    show_reason: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared paginated ban/appeal list renderer (index + detail buttons).

    Fetches only ``_PAGE_SIZE`` rows plus the real total per page turn,
    and keeps the header count exact even when a page tap comes in out of
    range (page is clamped before the slice is requested).
    """
    total, display_name = await asyncio.gather(
        count_call(target_id),
        _name(target_id),
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
            "ts": Safe(ts(ban)),
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


async def _per_chat_event_list(
    target_id: int,
    page: int,
    *,
    heading_name: str,
    db_call: Callable[..., Awaitable[list[Any]]],
    count_call: Callable[[int], Awaitable[int]],
    cb_prefix: str,
    locale: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared renderer for kicks/mutes; both have the same shape.

    Fetches only ``_PAGE_SIZE`` rows plus the real total per page turn,
    so the header stays exact and only the visible slice travels.
    """
    total, display_name = await asyncio.gather(
        count_call(target_id),
        _name(target_id),
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
        records = await db_call(target_id, skip=page * _PAGE_SIZE, limit=_PAGE_SIZE)
        records_failed = False
    except Exception:
        log.exception("check_flow %s list fetch failed for %d", cb_prefix, target_id)
        records = []
        records_failed = True
    if count_failed:
        # * Honest fallback when the count itself fails: show the fetched page.
        total = len(records)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    if not records:
        if count_failed or records_failed:
            text = t("checking.warns.db_fail", locale)
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])
        text = t(
            "checking.events.empty",
            locale,
            heading=Safe(bold(heading_name)),
            lower=heading_name.lower(),
            user=Safe(user_ref(target_id, display_name)),
        )
        return _maybe_caveat(text, locale, failed=count_failed), InlineKeyboardMarkup(
            [_back_to_check(target_id, locale)]
        )

    chat_ids = list({r["chat_id"] for r in records if "chat_id" in r})
    admin_ids = [r.get("admin_id", 0) for r in records if r.get("admin_id")]

    # * Resolve all titles + all admin names in parallel with batch query
    titles, admin_name_map = await asyncio.gather(
        db.groups_db.get_group_titles(chat_ids),
        db.users_cache.get_first_names_batch(admin_ids)
        if admin_ids
        else _async_const({}),
        return_exceptions=True,
    )
    if isinstance(titles, BaseException):
        titles = {}
    if isinstance(admin_name_map, BaseException):
        admin_name_map = {}

    lines = [
        t(
            "checking.events.header",
            locale,
            heading=Safe(bold(heading_name)),
            n=total,
            page=page + 1,
            pages=total_pages,
        )
        + "\n"
    ]
    base_idx = page * _PAGE_SIZE
    for i, rec in enumerate(records, start=1):
        ts = date_or_unknown(rec.get("timestamp"))
        stored_reason = rec.get("reason", None)
        reason_short = str(
            stored_reason
            if stored_reason is not None
            else t("checking.events.no_reason", locale, plain=True)
        )[:_REASON_PREVIEW_LEN]
        chat_id = rec.get("chat_id", 0)
        title = titles.get(chat_id) or str(chat_id)
        admin_id = rec.get("admin_id", 0)
        admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
        lines.append(
            t(
                "checking.events.item",
                locale,
                i=base_idx + i,
                ts=Safe(ts),
                title=title,
                reason=Safe(italic(reason_short)),
                admin=Safe(user_ref(admin_id, admin_name)),
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix, locale)
    if nav:
        rows.append(nav)
    rows.append(_back_to_check(target_id, locale))
    return _maybe_caveat(
        "\n".join(lines), locale, failed=count_failed
    ), InlineKeyboardMarkup(rows)


__all__ = ("Check",)
