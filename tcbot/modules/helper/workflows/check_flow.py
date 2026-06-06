# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Comprehensive user-profile view for /check: bans, warns, kicks, mutes, appeals."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.formatter import bold, code, esc, mention
from tcbot.utils.pagination import date_or_unknown, nav_row, paginate
from tcbot.utils.timedate_format import fmt_dt

log = logging.getLogger(__name__)

_PAGE_SIZE = 5
_GET_CHAT_TIMEOUT = 3.0
_REASON_PREVIEW_LEN = 80
_BUTTON_TITLE_MAX = 24


# ────────────────────────── Small helpers ───────────────────────── #


async def _resolve_user_info(bot: Bot, target_id: int) -> tuple[str, str | None]:
    """Return (display_name, username_or_None); fast-path cache hit, bounded Telegram fallback."""
    cached = await db.users_cache.get_user(target_id)
    fname = (cached.get("first_name") or "") if cached else ""
    uname = (cached.get("username") if cached else None) or None

    if fname and uname:
        return fname, uname

    try:
        chat = await asyncio.wait_for(
            bot.get_chat(target_id), timeout=_GET_CHAT_TIMEOUT
        )
        fname = fname or (chat.first_name or "")
        uname = uname or chat.username
    except Exception as exc:
        log.debug("get_chat(%s) failed: %s", target_id, exc)

    if not fname:
        fname = f"User {target_id}"
    return fname, uname


def _back_to_check(target_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("« Back", callback_data=f"check_main:{target_id}")]


async def _name(uid: int) -> str:
    """Fast cache-only name lookup; falls back to 'User <id>' string."""
    return await db.users_cache.get_first_name(uid, f"User {uid}")


async def _async_const(value: str) -> str:
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
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build the top-level profile view: identity + counts + drill-down keyboard."""
        # * All 9 reads are independent; fire them in parallel for a single round-trip.
        (
            (fname, uname),
            (role, role_by_id, role_at),
            active_ban,
            ban_total,
            appeal_total,
            warn_total,
            warn_groups,
            kick_total,
            mute_total,
        ) = await asyncio.gather(
            _resolve_user_info(bot, target_id),
            db.users_roles.role_meta(target_id),
            db.bans_db.get_active_ban(target_id),
            db.bans_db.user_ban_count(target_id),
            db.bans_db.user_appeal_count(target_id),
            db.warns_db.user_total_warns(target_id),
            db.warns_db.user_warn_groups(target_id),
            db.kicks_db.user_kick_count(target_id),
            db.mutes_db.user_mute_count(target_id),
        )

        role_label = db.users_roles.ROLE_LABEL.get(role, "None") if role else "None"
        uname_part = f"@{esc(uname)}" if uname else "(none)"
        active_part = f"Yes ({code(active_ban['ban_id'])})" if active_ban else "No"

        # * Build the rich role line with assignment metadata where available.
        role_lines = [f"Role: {bold(role_label)}"]
        if role and role != "founder" and role_by_id:
            by_name = await db.users_cache.get_first_name(
                role_by_id, f"User {role_by_id}"
            )
            role_lines.append(f"   Assigned by: {mention(role_by_id, by_name)}")
        if role and role != "founder" and role_at:
            role_lines.append(f"   Assigned at: {fmt_dt(role_at)}")
        role_block = "\n".join(role_lines)

        text = (
            f"{bold('Profile')}\n\n"
            f"Name: {mention(target_id, fname)}\n"
            f"ID: {code(str(target_id))}\n"
            f"Username: {uname_part}\n"
            f"{role_block}\n\n"
            f"{bold('Federation Activity')}\n\n"
            f"Active Ban: {active_part}\n"
            f"Total Bans: {ban_total}\n"
            f"Warnings: {warn_total} across {len(warn_groups)} group(s)\n"
            f"Kicks: {kick_total}\n"
            f"Mutes: {mute_total}\n"
            f"Appeals: {appeal_total}"
        )

        rows: list[list[InlineKeyboardButton]] = []
        rows.append(
            [
                InlineKeyboardButton(
                    f"Bans ({ban_total})",
                    callback_data=f"check_bans:{target_id}:0",
                ),
                InlineKeyboardButton(
                    f"Appeals ({appeal_total})",
                    callback_data=f"check_appeals:{target_id}:0",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"Warnings ({warn_total})",
                    callback_data=f"check_warns:{target_id}",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"Kicks ({kick_total})",
                    callback_data=f"check_kicks:{target_id}:0",
                ),
                InlineKeyboardButton(
                    f"Mutes ({mute_total})",
                    callback_data=f"check_mutes:{target_id}:0",
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
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban (active+inactive) with detail buttons per item."""
        bans = await db.bans_db.user_bans(target_id)
        chunk, total_pages, page = paginate(bans, page, _PAGE_SIZE)

        if not bans:
            text = (
                f"{bold('Bans')}\n\n"
                f"No ban records for {mention(target_id, await _name(target_id))}."
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id)])

        lines = [f"{bold('Bans')}: {len(bans)} total, page {page + 1}/{total_pages}\n"]
        item_btns: list[InlineKeyboardButton] = []
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            status = bold("Active") if ban.get("is_active") else "Inactive"
            ts = date_or_unknown(ban.get("timestamp"))
            reason_short = esc(str(ban.get("reason", "(no reason)"))[:60])
            lines.append(
                f"{base_idx + i}. {status} · {code(ban['ban_id'])} · {ts}\n"
                f"   <i>{reason_short}</i>"
            )
            item_btns.append(
                InlineKeyboardButton(
                    str(base_idx + i),
                    callback_data=f"check_ban_item:{target_id}:{ban['ban_id']}",
                )
            )

        rows: list[list[InlineKeyboardButton]] = []
        # * pair item buttons 3 per row
        for i in range(0, len(item_btns), 3):
            rows.append(item_btns[i : i + 3])
        nav = nav_row(page, total_pages, f"check_bans:{target_id}")
        if nav:
            rows.append(nav)
        rows.append(_back_to_check(target_id))
        return "\n".join(lines), InlineKeyboardMarkup(rows)

    @classmethod
    async def ban_detail(
        cls,
        target_id: int,
        ban_id: str,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Show a single ban's full detail (text + optional Proof button)."""
        ban = await db.bans_db.get_ban(ban_id)
        if not ban or ban.get("banned_user_id") != target_id:
            text = f"Ban {code(ban_id)} not found."
            return text, InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "« Back",
                            callback_data=f"check_bans:{target_id}:0",
                        )
                    ]
                ]
            )

        text, proof_link = await build_ban_detail(ban)
        rows: list[list[InlineKeyboardButton]] = []
        if proof_link:
            rows.append([InlineKeyboardButton("View Proof", url=proof_link)])
        appeal_link = ban.get("appeal_link")
        if appeal_link:
            rows.append([InlineKeyboardButton("View Appeal", url=appeal_link)])
        rows.append(
            [
                InlineKeyboardButton(
                    "« Back",
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
    ) -> tuple[str, InlineKeyboardMarkup]:
        """List groups where the user has warnings + count per group + drill-in buttons."""
        groups = await db.warns_db.user_warn_groups(target_id)
        if not groups:
            text = (
                f"{bold('Warnings')}\n\n"
                f"No warning records for {mention(target_id, await _name(target_id))}."
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id)])

        titles = await db.groups_db.get_group_titles([cid for cid, _ in groups])
        total = sum(c for _, c in groups)

        lines = [f"{bold('Warnings')}: {total} total across {len(groups)} group(s)\n"]
        rows: list[list[InlineKeyboardButton]] = []
        for cid, count in groups:
            title = titles.get(cid) or str(cid)
            lines.append(f"• {esc(title)}: {bold(str(count))}")
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{title[:_BUTTON_TITLE_MAX]} ({count})",
                        callback_data=f"check_warn_chat:{target_id}:{cid}:0",
                    )
                ]
            )

        rows.append(_back_to_check(target_id))
        return "\n".join(lines), InlineKeyboardMarkup(rows)

    @classmethod
    async def warns_in_group(
        cls,
        target_id: int,
        chat_id: int,
        page: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of individual warnings inside one chat."""
        warns, titles = await asyncio.gather(
            db.warns_db.get_warns(target_id, chat_id),
            db.groups_db.get_group_titles([chat_id]),
        )
        # * get_warns is oldest-first; reverse to newest-first for consistency
        warns = list(reversed(warns))
        chunk, total_pages, page = paginate(warns, page, _PAGE_SIZE)
        title = titles.get(chat_id) or str(chat_id)

        if not warns:
            text = f"{bold('Warnings in')} {esc(title)}\n\nNo warning records here."
            rows = [
                [
                    InlineKeyboardButton(
                        "« Back",
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
            f"{bold('Warnings in')} {esc(title)}: {len(warns)} total"
            f", page {page + 1}/{total_pages}\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, w in enumerate(chunk, start=1):
            ts = date_or_unknown(w.get("timestamp"))
            reason_short = esc(
                str(w.get("reason", "(no reason)"))[:_REASON_PREVIEW_LEN]
            )
            admin_id = w.get("admin_id", 0)
            admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
            lines.append(
                f"{base_idx + i}. {ts}\n"
                f"   <i>{reason_short}</i>\n"
                f"   By {mention(admin_id, admin_name)}"
            )

        rows = []
        nav = nav_row(page, total_pages, f"check_warn_chat:{target_id}:{chat_id}")
        if nav:
            rows.append(nav)
        rows.append(
            [
                InlineKeyboardButton(
                    "« Back",
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
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every kick record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Kicks",
            db_call=db.kicks_db.user_kicks,
            cb_prefix=f"check_kicks:{target_id}",
        )

    # ── Mutes drill-down ──────────────────────────────────────────────────

    @classmethod
    async def mutes_list(
        cls,
        target_id: int,
        page: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every mute record."""
        return await _per_chat_event_list(
            target_id,
            page,
            heading_name="Mutes",
            db_call=db.mutes_db.user_mutes,
            cb_prefix=f"check_mutes:{target_id}",
        )

    # ── Appeals drill-down ────────────────────────────────────────────────

    @classmethod
    async def appeals_list(
        cls,
        target_id: int,
        page: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every ban that ever had an appeal submitted."""
        all_bans = await db.bans_db.user_bans(target_id)
        bans = [b for b in all_bans if b.get("appeal_log_msg_id") is not None]
        chunk, total_pages, page = paginate(bans, page, _PAGE_SIZE)

        if not bans:
            text = (
                f"{bold('Appeals')}\n\n"
                f"No appeal records for {mention(target_id, await _name(target_id))}."
            )
            return text, InlineKeyboardMarkup([_back_to_check(target_id)])

        lines = [
            f"{bold('Appeals')}: {len(bans)} total, page {page + 1}/{total_pages}\n"
        ]
        item_btns: list[InlineKeyboardButton] = []
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            ts = date_or_unknown(ban.get("appeal_submitted_at") or ban.get("timestamp"))
            status = (
                f"{bold('Approved')} (unbanned)"
                if not ban.get("is_active")
                else "Pending / Rejected"
            )
            lines.append(
                f"{base_idx + i}. {status}\n   Ban ID: {code(ban['ban_id'])} · {ts}"
            )
            item_btns.append(
                InlineKeyboardButton(
                    str(base_idx + i),
                    callback_data=f"check_ban_item:{target_id}:{ban['ban_id']}",
                )
            )

        rows: list[list[InlineKeyboardButton]] = []
        for i in range(0, len(item_btns), 3):
            rows.append(item_btns[i : i + 3])
        nav = nav_row(page, total_pages, f"check_appeals:{target_id}")
        if nav:
            rows.append(nav)
        rows.append(_back_to_check(target_id))
        return "\n".join(lines), InlineKeyboardMarkup(rows)


# ─────────────────────── Shared list helper ─────────────────────── #


async def _per_chat_event_list(
    target_id: int,
    page: int,
    *,
    heading_name: str,
    db_call,
    cb_prefix: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Shared renderer for kicks/mutes; both have the same shape."""
    records = await db_call(target_id)
    chunk, total_pages, page = paginate(records, page, _PAGE_SIZE)

    if not records:
        text = (
            f"{bold(heading_name)}\n\n"
            f"No {heading_name.lower()} records for "
            f"{mention(target_id, await _name(target_id))}."
        )
        return text, InlineKeyboardMarkup([_back_to_check(target_id)])

    chat_ids = list({r["chat_id"] for r in chunk if "chat_id" in r})
    admin_ids = [r.get("admin_id", 0) for r in chunk if r.get("admin_id")]

    # * Resolve all titles + all admin names in parallel with batch query
    titles, admin_name_map = await asyncio.gather(
        db.groups_db.get_group_titles(chat_ids),
        db.users_cache.get_first_names_batch(admin_ids)
        if admin_ids
        else _async_const({}),
    )

    lines = [
        f"{bold(heading_name)}: {len(records)} total, page {page + 1}/{total_pages}\n"
    ]
    base_idx = page * _PAGE_SIZE
    for i, rec in enumerate(chunk, start=1):
        ts = date_or_unknown(rec.get("timestamp"))
        reason_short = esc(str(rec.get("reason", "(no reason)"))[:_REASON_PREVIEW_LEN])
        chat_id = rec.get("chat_id", 0)
        title = titles.get(chat_id) or str(chat_id)
        admin_id = rec.get("admin_id", 0)
        admin_name = admin_name_map.get(admin_id, "Admin") if admin_id else "Admin"
        lines.append(
            f"{base_idx + i}. {ts}\n"
            f"   Group: {esc(title)}\n"
            f"   <i>{reason_short}</i>\n"
            f"   By {mention(admin_id, admin_name)}"
        )

    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix)
    if nav:
        rows.append(nav)
    rows.append(_back_to_check(target_id))
    return "\n".join(lines), InlineKeyboardMarkup(rows)


__all__ = ("Check", "build_ban_detail")
