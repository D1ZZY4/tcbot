# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Comprehensive user-profile view for /check: bans, warns, kicks, mutes, appeals."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.identity import Identity, classify, profile_note
from tcbot.modules.helper.keyboards import back_to_module_kb, paged_drill_kb
from tcbot.utils.formatter import bold, code, italic, mention
from tcbot.utils.i18n import Safe, t
from tcbot.utils.pagination import date_or_unknown, nav_row, paginate
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

log = logging.getLogger(__name__)

_PAGE_SIZE = 5
_REASON_PREVIEW_LEN = 80
_BAN_LIST_REASON_LEN = 60
_BUTTON_TITLE_MAX = 24
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
    return [
        InlineKeyboardButton(
            t("button.back", locale, plain=True),
            callback_data=f"check_main:{target_id}",
        )
    ]


async def _name(uid: int) -> str:
    """Fast cache-only name lookup; falls back to numeric ID string."""
    return await db.users_cache.get_first_name(uid, str(uid))


async def _async_const(value: Any) -> Any:
    """Wrap a constant in an async coroutine so gather() can mix it with awaits."""
    return value


# ─────────────────────────── Check class ────────────────────────── #


class Check:
    """All view builders for the /check user-profile command."""

    PAGE_SIZE = _PAGE_SIZE

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
                    by=Safe(mention(role_by_id, by_name)),
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
            + f"{t('checking.profile.name', locale, user=Safe(mention(target_id, fname)))}\n"
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

        rows: list[list[InlineKeyboardButton]] = []
        rows.append(
            [
                InlineKeyboardButton(
                    t("checking.profile.button.bans", locale, n=ban_total, plain=True),
                    callback_data=f"check_bans:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.appeals",
                        locale,
                        n=appeal_total,
                        plain=True,
                    ),
                    callback_data=f"check_appeals:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.warnings",
                        locale,
                        n=fed_warn_total,
                        plain=True,
                    ),
                    callback_data=f"check_warns:{target_id}",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.kicks",
                        locale,
                        n=kick_total,
                        plain=True,
                    ),
                    callback_data=f"check_kicks:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.mutes",
                        locale,
                        n=mute_total,
                        plain=True,
                    ),
                    callback_data=f"check_mutes:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ]
        )

        return text, InlineKeyboardMarkup(rows)

    # ── Bans drill-down ───────────────────────────────────────────────────

    @classmethod
    async def bans_list(
        cls,
        target_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban (active+inactive) with detail buttons per item."""
        # * Fetch ban history and resolve display name in parallel; the name is
        # * needed for the empty-list message and the list header alike.
        bans, display_name = await asyncio.gather(
            db.bans_db.user_bans(target_id),
            _name(target_id),
            return_exceptions=True,
        )
        if isinstance(bans, BaseException):
            bans = []
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        chunk, total_pages, page = paginate(bans, page, _PAGE_SIZE)

        if not bans:
            text = t(
                "checking.bans.empty",
                locale,
                user=Safe(mention(target_id, display_name)),
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

        lines = [
            t(
                "checking.bans.header",
                locale,
                n=len(bans),
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        items: list[tuple[str, str]] = []
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            status = (
                t("checking.bans.active", locale)
                if ban.get("is_active")
                else t("checking.bans.inactive", locale)
            )
            ts = date_or_unknown(ban.get("timestamp"))
            stored_reason = ban.get("reason", None)
            reason_short = str(
                stored_reason
                if stored_reason is not None
                else t("checking.events.no_reason", locale, plain=True)
            )[:_BAN_LIST_REASON_LEN]
            lines.append(
                t(
                    "checking.bans.item",
                    locale,
                    i=base_idx + i,
                    status=Safe(status),
                    ban=Safe(code(ban.get("ban_id", ""))),
                    ts=Safe(ts),
                    reason=Safe(italic(reason_short)),
                )
            )
            items.append(
                (
                    str(base_idx + i),
                    f"check_ban_item:{target_id}:{ban.get('ban_id', '')}",
                )
            )

        return "\n".join(lines), paged_drill_kb(
            items,
            page=page,
            total_pages=total_pages,
            nav_prefix=f"check_bans:{target_id}",
            back_callback=f"check_main:{target_id}",
            per_row=_BTNS_PER_ROW,
        )

    @classmethod
    async def ban_detail(
        cls,
        target_id: int,
        ban_id: str,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Show a single ban's full detail (text + optional Proof button)."""
        ban = await db.bans_db.get_ban(ban_id)
        if not ban or ban.get("banned_user_id") != target_id:
            text = t(
                "checking.bans.not_found",
                locale,
                ban=Safe(code(ban_id)),
            )
            return text, back_to_module_kb(f"check_bans:{target_id}:0", locale)

        text, proof_link = await build_ban_detail(ban, locale=locale)
        rows: list[list[InlineKeyboardButton]] = []
        if proof_link:
            rows.append(
                [
                    InlineKeyboardButton(
                        t("button.view_proof", locale, plain=True),
                        url=proof_link,
                        style=KeyboardButtonStyle.PRIMARY,
                    )
                ]
            )
        appeal_link = ban.get("appeal_link")
        if appeal_link:
            rows.append(
                [
                    InlineKeyboardButton(
                        t("button.view_appeal", locale, plain=True),
                        url=appeal_link,
                        style=KeyboardButtonStyle.PRIMARY,
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data=f"check_bans:{target_id}:0",
                )
            ]
        )
        return text, InlineKeyboardMarkup(rows)

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
            groups = []
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        if not groups:
            text = t(
                "checking.warns.empty",
                locale,
                user=Safe(mention(target_id, display_name)),
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

        titles = await db.groups_db.get_group_titles([cid for cid, _ in groups])
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
        rows: list[list[InlineKeyboardButton]] = []
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
            rows.append(
                [
                    InlineKeyboardButton(
                        t(
                            "checking.warns.group_button",
                            locale,
                            title=title[:_BUTTON_TITLE_MAX],
                            n=count,
                            plain=True,
                        ),
                        callback_data=f"check_warn_chat:{target_id}:{cid}:0",
                        style=KeyboardButtonStyle.PRIMARY,
                    )
                ]
            )

        rows.append(_back_to_check(target_id, locale))
        return "\n".join(lines), InlineKeyboardMarkup(rows)

    @classmethod
    async def warns_in_group(
        cls,
        target_id: int,
        chat_id: int,
        page: int,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of individual warnings inside one chat."""
        warns, titles = await asyncio.gather(
            db.warns_db.get_warns(target_id, chat_id),
            db.groups_db.get_group_titles([chat_id]),
            return_exceptions=True,
        )
        if isinstance(warns, BaseException):
            warns = []
        if isinstance(titles, BaseException):
            titles = {}
        # * get_warns is oldest-first; reverse to newest-first for consistency
        warns = list(reversed(warns))
        chunk, total_pages, page = paginate(warns, page, _PAGE_SIZE)
        title = titles.get(chat_id) or str(chat_id)

        if not warns:
            text = t("checking.warns.in_empty", locale, title=title)
            rows = [
                [
                    InlineKeyboardButton(
                        t("button.back", locale, plain=True),
                        callback_data=f"check_warns:{target_id}",
                    )
                ]
            ]
            return text, InlineKeyboardMarkup(rows)

        # * Resolve admin names with batch query
        admin_ids = [w.get("admin_id", 0) for w in chunk if w.get("admin_id")]
        admin_name_map = (
            await db.users_cache.get_first_names_batch(admin_ids) if admin_ids else {}
        )

        lines = [
            t(
                "checking.warns.in_header",
                locale,
                title=title,
                n=len(warns),
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, w in enumerate(chunk, start=1):
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
                    admin=Safe(mention(admin_id, admin_name)),
                )
            )

        rows = []
        nav = nav_row(page, total_pages, f"check_warn_chat:{target_id}:{chat_id}")
        if nav:
            rows.append(nav)
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data=f"check_warns:{target_id}",
                )
            ]
        )
        return "\n".join(lines), InlineKeyboardMarkup(rows)

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
        all_bans, display_name = await asyncio.gather(
            db.bans_db.user_appealable_bans(target_id),
            _name(target_id),
            return_exceptions=True,
        )
        if isinstance(all_bans, BaseException):
            all_bans = []
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        bans = all_bans
        chunk, total_pages, page = paginate(bans, page, _PAGE_SIZE)

        if not bans:
            text = t(
                "checking.appeals_list.empty",
                locale,
                user=Safe(mention(target_id, display_name)),
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

        lines = [
            t(
                "checking.appeals_list.header",
                locale,
                n=len(bans),
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        items: list[tuple[str, str]] = []
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            ts = date_or_unknown(ban.get("appeal_submitted_at") or ban.get("timestamp"))
            status = (
                t("checking.appeals_list.approved", locale)
                if not ban.get("is_active")
                else t("checking.appeals_list.pending", locale)
            )
            lines.append(
                t(
                    "checking.appeals_list.item",
                    locale,
                    i=base_idx + i,
                    status=Safe(status),
                    ban=Safe(code(ban.get("ban_id", ""))),
                    ts=Safe(ts),
                )
            )
            items.append(
                (
                    str(base_idx + i),
                    f"check_ban_item:{target_id}:{ban.get('ban_id', '')}",
                )
            )

        return "\n".join(lines), paged_drill_kb(
            items,
            page=page,
            total_pages=total_pages,
            nav_prefix=f"check_appeals:{target_id}",
            back_callback=f"check_main:{target_id}",
            per_row=_BTNS_PER_ROW,
        )


# ─────────────────────── Shared list helper ─────────────────────── #


async def _per_chat_event_list(
    target_id: int,
    page: int,
    *,
    heading_name: str,
    db_call: Callable[[int], Awaitable[list[Any]]],
    cb_prefix: str,
    locale: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared renderer for kicks/mutes; both have the same shape."""
    records, display_name = await asyncio.gather(
        db_call(target_id),
        _name(target_id),
        return_exceptions=True,
    )
    if isinstance(records, BaseException):
        records = []
    if isinstance(display_name, BaseException):
        display_name = str(target_id)
    chunk, total_pages, page = paginate(records, page, _PAGE_SIZE)

    if not records:
        text = t(
            "checking.events.empty",
            locale,
            heading=Safe(bold(heading_name)),
            lower=heading_name.lower(),
            user=Safe(mention(target_id, display_name)),
        )
        return text, InlineKeyboardMarkup([_back_to_check(target_id, locale)])

    chat_ids = list({r["chat_id"] for r in chunk if "chat_id" in r})
    admin_ids = [r.get("admin_id", 0) for r in chunk if r.get("admin_id")]

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
            n=len(records),
            page=page + 1,
            pages=total_pages,
        )
        + "\n"
    ]
    base_idx = page * _PAGE_SIZE
    for i, rec in enumerate(chunk, start=1):
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
                admin=Safe(mention(admin_id, admin_name)),
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix)
    if nav:
        rows.append(nav)
    rows.append(_back_to_check(target_id, locale))
    return "\n".join(lines), InlineKeyboardMarkup(rows)


__all__ = ("Check",)
