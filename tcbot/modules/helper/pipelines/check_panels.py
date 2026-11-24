# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Comprehensive user-profile view for /check: bans, warns, kicks, mutes, appeals."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from telegram import Bot, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.buttons import (
    back_to_module_btn,
    check_back_markup,
    check_back_row,
    check_paged_markup,
    check_profile_btn,
    check_warn_groups_btn,
    check_warns_back_row,
    detail_btn,
    nav_row,
    paged_drill_btn,
)
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.identity import Identity, classify, profile_note
from tcbot.modules.helper.messages.rich_format import divider, footer, heading
from tcbot.modules.helper.messages.rich_table import table
from tcbot.modules.helper.messages.rich_text import blocks
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, bold, code, esc, italic, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import clamp_page
from tcbot.utils.time_and_date import (
    date_or_unknown,
    fmt_date,
    fmt_duration,
    fmt_time,
    time_or_unknown,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

# ───────────────────────── Shared helpers ───────────────────────── #


_PAGE_SIZE = 5
_REASON_PREVIEW_LEN = 80
_BAN_LIST_REASON_LEN = 60
_BTNS_PER_ROW = 3


async def _resolve_user_info(bot: Bot, target_id: int) -> tuple[str, str | None]:
    """Return display name instantly from cache; refresh in background."""
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


def _maybe_caveat(text: str, locale: str | None, *, failed: bool) -> str:
    """Append the incomplete-counters note when a count read failed."""
    if failed:
        text += f"\n\n{t('checking.profile.caveat', locale)}"
    return text


async def _name(uid: int) -> str:
    """Fast cache-only name lookup; falls back to numeric ID string."""
    return await db.users_cache.get_first_name(uid, str(uid))


async def _async_const(value: Any) -> Any:
    """Wrap a constant so gather() can mix it with awaits."""
    return value


def _ban_ts(ban: dict[str, Any], locale: str | None = None) -> tuple[str, str]:
    ts = ban.get("timestamp")
    return date_or_unknown(ts, locale), time_or_unknown(ts, locale)


def _appeal_ts(ban: dict[str, Any], locale: str | None = None) -> tuple[str, str]:
    ts = ban.get("appeal_submitted_at") or ban.get("timestamp")
    return date_or_unknown(ts, locale), time_or_unknown(ts, locale)


# ────────────────────────── Profile view ────────────────────────── #


class CheckProfileMixin:
    """Top-level profile builder for the /check command."""

    @classmethod
    async def profile(
        cls,
        bot: Bot,
        target_id: int,
        *,
        executor_id: int | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build the top-level profile view: identity plus counts."""
        _reads: list[Any] = [
            _resolve_user_info(bot, target_id),
            db.users_roles.role_meta(target_id),
            db.bans_db.get_active_ban(target_id),
            db.mutes_db.get_active_mute(target_id),
            db.bans_db.user_ban_count(target_id),
            db.bans_db.user_appeal_count(target_id),
            db.warns_db.user_total_warns(target_id),
            db.warns_db.user_warn_groups(target_id),
            db.kicks_db.user_kick_count(target_id),
            db.mutes_db.user_mute_count(target_id),
        ]
        if executor_id is not None:
            _reads.append(classify(bot, executor_id, target_id))
        _results = await asyncio.gather(*_reads, return_exceptions=True)
        throw_if_cancelled(_results)
        r_user_info = _results[0]
        r_role_meta = _results[1]
        ban_failed = isinstance(_results[2], BaseException)
        mute_failed = isinstance(_results[3], BaseException)
        counts_failed = any(isinstance(r, BaseException) for r in _results[4:10])
        active_ban = _results[2] if not ban_failed else None
        active_mute = _results[3] if not mute_failed else None
        ban_total = _results[4] if not isinstance(_results[4], BaseException) else 0
        appeal_total = _results[5] if not isinstance(_results[5], BaseException) else 0
        warn_total = _results[6] if not isinstance(_results[6], BaseException) else 0
        _wg = _results[7] if not isinstance(_results[7], BaseException) else None
        warn_groups: list[tuple[int, int]] = (
            cast("list[tuple[int, int]]", _wg) if _wg is not None else []
        )
        # * The federation total is the sum of the per-group counts that the
        # * warn-group read already returned, so a second query would read
        # * the same rows again.
        fed_warn_total = sum(count for _, count in warn_groups)
        kick_total = _results[8] if not isinstance(_results[8], BaseException) else 0
        mute_total = _results[9] if not isinstance(_results[9], BaseException) else 0
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
        identity_note: str | None = None
        if len(_results) > 10:
            r_ident = _results[10]
            if not isinstance(r_ident, BaseException):
                identity_note = profile_note(cast("Identity", r_ident), locale)
        role_label = (
            db.users_roles.role_label(role)
            if role
            else (
                t("checking.profile.unknown", locale)
                if isinstance(r_role_meta, BaseException)
                else t("checking.profile.regular", locale)
            )
        )
        active_ban_doc = cast("BanDoc | None", active_ban)
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

        def label(key: str) -> str:
            return t(f"checking.profile.table.{key}", locale, plain=True)

        uname_value = (
            t("checking.profile.table.username_value", locale, name=esc(uname))
            if uname
            else t("checking.profile.username_none", locale, plain=True)
        )
        identity_rows: list[list[str]] = [
            [label("name"), Safe(user_ref(target_id, fname))],
            [label("id"), Safe(code(str(target_id)))],
            [label("username"), Safe(uname_value)],
            [label("role"), Safe(bold(role_label))],
        ]
        if role and role != "owner" and role_by_id:
            by_name = await db.users_cache.get_first_name(role_by_id, str(role_by_id))
            identity_rows.append(
                [label("assigned_by"), Safe(user_ref(role_by_id, by_name))]
            )
        if role and role != "owner" and role_at:
            identity_rows.append(
                [
                    label("assigned_at"),
                    Safe(f"{fmt_date(role_at)} | {fmt_time(role_at)}"),
                ]
            )
        headers = [label("field"), label("value")]
        activity_rows: list[list[str]] = [
            [label("active_ban"), Safe(active_part)],
            [label("active_mute"), Safe(active_mute_part)],
            [label("total_bans"), str(ban_total)],
            [
                label("warnings"),
                Safe(
                    t(
                        "checking.profile.table.warnings_detail",
                        locale,
                        active=fed_warn_total,
                        groups=len(warn_groups) if warn_groups is not None else 0,
                        total=warn_total,
                    )
                ),
            ],
            [label("kicks"), str(kick_total)],
            [label("mutes"), str(mute_total)],
            [label("appeals"), str(appeal_total)],
        ]
        blocks_out = [
            heading(t("checking.profile.title", locale, plain=True), 2),
            divider(),
            table(headers, identity_rows, raw_cells=True, compact=True, striped=True),
            heading(t("checking.profile.activity", locale, plain=True), 2),
            divider(),
            table(headers, activity_rows, raw_cells=True, compact=True, striped=True),
        ]
        if identity_note:
            blocks_out.insert(0, identity_note)
        if counts_failed:
            blocks_out.append(footer(t("checking.profile.caveat", locale, plain=True)))
        return "\n".join(blocks_out), check_profile_btn(
            target_id,
            ban_total=ban_total,
            appeal_total=appeal_total,
            fed_warn_total=fed_warn_total,
            kick_total=kick_total,
            mute_total=mute_total,
            locale=locale,
        )


# ────────────────────── Ban and appeal lists ────────────────────── #


class CheckBansMixin:
    """Ban and appeal drill-down builders."""

    @classmethod
    async def bans_list(
        cls, target_id: int, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban with detail buttons per item."""
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
        cls, target_id: int, ban_id: str, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Show a single ban full detail."""
        try:
            ban = await db.bans_db.get_ban(ban_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            text = t(
                "checking.bans.db_fail",
                locale,
                ban=Safe(code(ban_id)),
            )
            return blocks(text), back_to_module_btn(f"check_bans:{target_id}:0", locale)
        if not ban or ban.get("target_user_id") != target_id:
            text = t(
                "checking.bans.not_found",
                locale,
                ban=Safe(code(ban_id)),
            )
            return blocks(text), back_to_module_btn(f"check_bans:{target_id}:0", locale)
        text, proof_link = await build_ban_detail(ban, locale=locale)
        return blocks(text), detail_btn(
            back_callback=f"check_bans:{target_id}:0",
            proof_link=proof_link,
            appeal_link=ban.get("appeal_link"),
            locale=locale,
        )

    @classmethod
    async def appeals_list(
        cls, target_id: int, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban that ever had an appeal."""
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


class _PagedRecords(NamedTuple):
    """One page of per-user records with the paging state that produced it."""

    records: list[Any]
    total: int
    total_pages: int
    page: int
    display_name: str
    count_failed: bool
    fetch_failed: bool


async def _paged_records(
    target_id: int,
    page: int,
    *,
    db_call: Callable[..., Awaitable[list[Any]]],
    count_call: Callable[[int], Awaitable[int]],
    log_label: str,
) -> _PagedRecords:
    """Fetch one page of per-user records together with its total count.

    Single owner for the paging prologue every drill-down list shares: the
    count and the display name resolve in parallel, the page fetch follows
    because it needs the page number the count produces, and a failed count
    falls back to the fetched row count so a partial outage still renders
    the rows that could be read.
    """
    total, display_name = await asyncio.gather(
        count_call(target_id),
        _name(target_id),
        return_exceptions=True,
    )
    throw_if_cancelled((total, display_name))
    if isinstance(display_name, BaseException):
        display_name = str(target_id)
    if isinstance(total, BaseException) or not isinstance(total, int):
        total = 0
        count_failed = True
    else:
        count_failed = False
    total_pages, page = clamp_page(total, page, _PAGE_SIZE)
    try:
        records = await db_call(target_id, skip=page * _PAGE_SIZE, limit=_PAGE_SIZE)
        fetch_failed = False
    except Exception:
        log.exception("check_panels %s list fetch failed for %d", log_label, target_id)
        records = []
        fetch_failed = True
    if count_failed:
        total = len(records)
        total_pages, _ = clamp_page(total, page, _PAGE_SIZE)
    return _PagedRecords(
        records=records,
        total=total,
        total_pages=total_pages,
        page=page,
        display_name=display_name,
        count_failed=count_failed,
        fetch_failed=fetch_failed,
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
    ts: Callable[..., tuple[str, str]],
    show_reason: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared paginated ban/appeal list renderer."""
    paged = await _paged_records(
        target_id,
        page,
        db_call=db_call,
        count_call=count_call,
        log_label=key_prefix,
    )
    total, total_pages, page = paged.total, paged.total_pages, paged.page
    display_name, count_failed = paged.display_name, paged.count_failed
    chunk = paged.records
    if not chunk:
        if count_failed or paged.fetch_failed:
            text = t("checking.warns.db_fail", locale)
            return blocks(text), check_back_markup(target_id, locale)
        text = t(
            f"checking.{key_prefix}.empty",
            locale,
            user=Safe(user_ref(target_id, display_name)),
        )
        return blocks(
            _maybe_caveat(text, locale, failed=count_failed)
        ), check_back_markup(target_id, locale)
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
        }
        item_date, item_time = ts(ban, locale)
        item_kwargs["date"] = Safe(item_date)
        item_kwargs["time"] = Safe(item_time)
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
    return blocks(
        _maybe_caveat(
            "\n".join(lines), locale, failed=count_failed or paged.fetch_failed
        )
    ), paged_drill_btn(
        items,
        page=page,
        total_pages=total_pages,
        nav_prefix=f"{nav_prefix}:{target_id}",
        back_callback=f"check_main:{target_id}",
        per_row=_BTNS_PER_ROW,
        locale=locale,
    )


# ───────────────────── Warn, kick, mute lists ───────────────────── #


class CheckEventsMixin:
    """Warn, kick, and mute drill-down builders."""

    @classmethod
    async def warns_by_group(
        cls, target_id: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """List groups where the user has warnings plus drill-in buttons."""
        groups, display_name = await asyncio.gather(
            db.warns_db.user_warn_groups(target_id),
            _name(target_id),
            return_exceptions=True,
        )
        throw_if_cancelled((groups, display_name))
        if isinstance(groups, BaseException):
            text = t("checking.warns.db_fail", locale)
            return blocks(text), check_back_markup(target_id, locale)
        if isinstance(display_name, BaseException):
            display_name = str(target_id)
        if not groups:
            text = t(
                "checking.warns.empty",
                locale,
                user=Safe(user_ref(target_id, display_name)),
            )
            return blocks(text), check_back_markup(target_id, locale)
        try:
            titles = await db.groups_db.get_group_titles([cid for cid, _ in groups])
        except Exception as exc:
            log.debug("Group titles fallback for check view: %s", exc)
            titles = {}
        total = sum(c for _, c in groups)
        warn_groups: list[tuple[str, int, int]] = []
        rows: list[list[str]] = []
        for cid, count in groups:
            title = titles.get(cid) or str(cid)
            rows.append([Safe(esc(title)), Safe(bold(str(count)))])
            warn_groups.append((title, count, cid))
        text = (
            heading(
                t(
                    "checking.warns.header",
                    locale,
                    plain=True,
                    n=total,
                    groups=len(groups),
                ),
                2,
            )
            + "\n"
            + divider()
            + "\n"
            + table(
                [
                    t("checking.warns.table.group", locale, plain=True),
                    t("checking.warns.table.count", locale, plain=True),
                ],
                rows,
                raw_cells=True,
                compact=True,
                striped=True,
            )
        )
        return text, check_warn_groups_btn(target_id, warn_groups, locale=locale)

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
        throw_if_cancelled((count, titles))
        if isinstance(titles, BaseException):
            titles = {}
        if isinstance(count, BaseException) or not isinstance(count, int):
            count = 0
            count_failed = True
        else:
            count_failed = False
        total_pages, page = clamp_page(count, page, _PAGE_SIZE)
        try:
            warns = await db.warns_db.get_warns(
                target_id,
                chat_id,
                skip=page * _PAGE_SIZE,
                limit=_PAGE_SIZE,
                newest_first=True,
            )
            warns_failed = False
        except Exception:
            log.exception(
                "check_panels warns_in_group fetch failed for %d/%d", target_id, chat_id
            )
            warns = []
            warns_failed = True
        if count_failed:
            count = len(warns)
            total_pages, _ = clamp_page(count, page, _PAGE_SIZE)
        title = titles.get(chat_id) or str(chat_id)
        if not warns:
            text = t("checking.warns.in_empty", locale, title=title)
            return blocks(
                _maybe_caveat(text, locale, failed=count_failed or warns_failed)
            ), check_paged_markup(None, check_warns_back_row(target_id, locale))
        admin_ids = [w.get("actor_user_id", 0) for w in warns if w.get("actor_user_id")]
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
            raw_ts = w.get("timestamp")
            date_s = date_or_unknown(raw_ts, locale)
            time_s = time_or_unknown(raw_ts, locale)
            stored_reason = w.get("reason", None)
            reason_short = str(
                stored_reason
                if stored_reason is not None
                else t("checking.events.no_reason", locale, plain=True)
            )[:_REASON_PREVIEW_LEN]
            admin_id = w.get("actor_user_id", 0)
            admin_fallback = t("checking.profile.admin_fallback", locale, plain=True)
            admin_name = (
                admin_name_map.get(admin_id, admin_fallback)
                if admin_id
                else admin_fallback
            )
            lines.append(
                t(
                    "checking.warns.in_item",
                    locale,
                    i=base_idx + i,
                    date=Safe(date_s),
                    time=Safe(time_s),
                    reason=Safe(italic(reason_short)),
                    admin=Safe(user_ref(admin_id, admin_name)),
                )
            )
        nav = nav_row(
            page, total_pages, f"check_warn_chat:{target_id}:{chat_id}", locale
        )
        return blocks(
            _maybe_caveat("\n".join(lines), locale, failed=count_failed)
        ), check_paged_markup(nav, check_warns_back_row(target_id, locale))

    @classmethod
    async def kicks_list(
        cls, target_id: int, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every kick record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_key="kicks_heading",
            lower_key="kicks_lower",
            db_call=db.kicks_db.user_kicks,
            count_call=db.kicks_db.user_kick_count,
            cb_prefix=f"check_kicks:{target_id}",
            show_status=True,
            locale=locale,
        )

    @classmethod
    async def mutes_list(
        cls, target_id: int, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every mute record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_key="mutes_heading",
            lower_key="mutes_lower",
            db_call=db.mutes_db.user_mutes,
            count_call=db.mutes_db.user_mute_count,
            cb_prefix=f"check_mutes:{target_id}",
            show_duration=True,
            locale=locale,
        )


async def _per_chat_event_list(
    target_id: int,
    page: int,
    *,
    heading_key: str,
    lower_key: str,
    db_call: Callable[..., Awaitable[list[Any]]],
    count_call: Callable[[int], Awaitable[int]],
    cb_prefix: str,
    show_duration: bool = False,
    show_status: bool = False,
    locale: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared renderer for kicks/mutes lists."""
    paged = await _paged_records(
        target_id,
        page,
        db_call=db_call,
        count_call=count_call,
        log_label=cb_prefix,
    )
    total, total_pages, page = paged.total, paged.total_pages, paged.page
    display_name, count_failed = paged.display_name, paged.count_failed
    records = paged.records
    if not records:
        if count_failed or paged.fetch_failed:
            text = t("checking.warns.db_fail", locale)
            return blocks(text), check_back_markup(target_id, locale)
        text = t(
            "checking.events.empty",
            locale,
            heading=Safe(bold(t(f"checking.events.{heading_key}", locale, plain=True))),
            lower=t(f"checking.events.{lower_key}", locale, plain=True),
            user=Safe(user_ref(target_id, display_name)),
        )
        return blocks(
            _maybe_caveat(text, locale, failed=count_failed)
        ), check_back_markup(target_id, locale)
    chat_ids = list({r["chat_id"] for r in records if "chat_id" in r})
    admin_ids = [r.get("actor_user_id", 0) for r in records if r.get("actor_user_id")]
    titles, admin_name_map = await asyncio.gather(
        db.groups_db.get_group_titles(chat_ids),
        db.users_cache.get_first_names_batch(admin_ids)
        if admin_ids
        else _async_const({}),
        return_exceptions=True,
    )
    throw_if_cancelled((titles, admin_name_map))
    if isinstance(titles, BaseException):
        titles = {}
    if isinstance(admin_name_map, BaseException):
        admin_name_map = {}
    lines = [
        t(
            "checking.events.header",
            locale,
            heading=Safe(bold(t(f"checking.events.{heading_key}", locale, plain=True))),
            n=total,
            page=page + 1,
            pages=total_pages,
        )
        + "\n"
    ]
    base_idx = page * _PAGE_SIZE
    for i, rec in enumerate(records, start=1):
        raw_ts = rec.get("timestamp")
        date_s = date_or_unknown(raw_ts, locale)
        time_s = time_or_unknown(raw_ts, locale)
        stored_reason = rec.get("reason", None)
        reason_short = str(
            stored_reason
            if stored_reason is not None
            else t("checking.events.no_reason", locale, plain=True)
        )[:_REASON_PREVIEW_LEN]
        chat_id = rec.get("chat_id", 0)
        title = titles.get(chat_id) or str(chat_id)
        admin_id = rec.get("actor_user_id", 0)
        admin_fallback = t("checking.profile.admin_fallback", locale, plain=True)
        admin_name = (
            admin_name_map.get(admin_id, admin_fallback) if admin_id else admin_fallback
        )
        if show_duration:
            requested_secs = rec.get("requested_duration_secs")
            stored_secs = rec.get("duration_secs")
            requested = (
                fmt_duration(timedelta(seconds=requested_secs), locale)
                if isinstance(requested_secs, int)
                else fmt_duration(timedelta(seconds=stored_secs), locale)
                if isinstance(stored_secs, int)
                else t("muting.duration.permanent", locale, plain=True)
            )
            stored = (
                fmt_duration(timedelta(seconds=stored_secs), locale)
                if isinstance(stored_secs, int)
                else t("muting.duration.permanent", locale, plain=True)
            )
            lines.append(
                t(
                    "checking.events.mute_item",
                    locale,
                    i=base_idx + i,
                    date=Safe(date_s),
                    time=Safe(time_s),
                    title=title,
                    requested=requested,
                    stored=stored,
                    reason=Safe(italic(reason_short)),
                    admin=Safe(user_ref(admin_id, admin_name)),
                )
            )
        else:
            line = t(
                "checking.events.item",
                locale,
                i=base_idx + i,
                date=Safe(date_s),
                time=Safe(time_s),
                title=title,
                reason=Safe(italic(reason_short)),
                admin=Safe(user_ref(admin_id, admin_name)),
            )
            if show_status and rec.get("status") == "failed":
                line += "\n   " + t("checking.events.kick_failed", locale)
            lines.append(line)
    nav = nav_row(page, total_pages, cb_prefix, locale)
    return blocks(
        _maybe_caveat("\n".join(lines), locale, failed=count_failed)
    ), check_paged_markup(nav, check_back_row(target_id, locale))


# ─────────────────────────── Check views ────────────────────────── #


class Check(CheckProfileMixin, CheckBansMixin, CheckEventsMixin):
    """All view builders for the /check user-profile command."""
